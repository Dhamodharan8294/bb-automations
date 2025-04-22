from collections import OrderedDict
from math import ceil
from typing import Optional, cast

import constructs
from aws_cdk import Duration
from aws_cdk.aws_apigateway import SpecRestApi
from aws_cdk.aws_cloudwatch import Alarm, AlarmBase, AlarmStatusWidget, ComparisonOperator, Dashboard, IAlarmAction, \
    IMetric, MathExpression, TreatMissingData, Unit
from aws_cdk.aws_cloudwatch_actions import SnsAction
from aws_cdk.aws_lambda import Alias, Function
from bb_fnds.cdk_constructs import pipeline_forge
from bb_fnds.cdk_constructs.sns import Topic

from cdk.core.stack_inputs import AlarmConfigOverrides, CoreStackInputs

DEFAULT_ALARM_PERIOD = Duration.minutes(1)


class CloudWatch(constructs.Construct):
    warning_topic: Optional[Topic] = None
    critical_topic: Optional[Topic] = None

    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: CoreStackInputs):
        super().__init__(stack, 'CustomAlarms')
        self.stack = stack
        self.stack_inputs = stack_inputs

        # This topic is referenced by tenant stacks - do not remove or allow the ID/ARN to change
        if stack_inputs.alarms.pagerduty.warning:
            self.warning_topic = Topic(self, 'FndsConnectorAlarmTopicWarning', unencrypted=True)
        if stack_inputs.alarms.pagerduty.critical:
            self.critical_topic = Topic(self, 'FndsConnectorAlarmTopicCritical', unencrypted=True)

        self._rest_lambdas: list[Function] = []

        self._alarms: list[AlarmBase] = []

        if suffix := self.stack_inputs.alarms.dashboard_suffix:
            dashboard_name = f'{stack.stack_name}-{suffix}'
        else:
            dashboard_name = stack.stack_name
        self.dashboard = Dashboard(self, 'Dashboard', dashboard_name=dashboard_name)

    def api_gateway_add_alarms(self, api: SpecRestApi) -> list[Alarm]:
        """Adds a number of alarms for the API Gateway"""

        alarms = []

        alarm_config: AlarmConfigOverrides = self.stack_inputs.api_gateway.latency_alarm_config
        alarm_config.set_defaults(evaluation_periods=5, threshold=550)
        alarms.append(
            self._create_alarm(
                'ApiGatewayLatency',
                topic=self.warning_topic,
                description='Alarm if the 95th percentile of REST API latency is too high.',
                metric=api.metric_latency(statistic='p95', period=DEFAULT_ALARM_PERIOD),
                evaluation_periods=alarm_config.evaluation_periods,
                threshold=alarm_config.threshold,
                comparison_operator=ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=TreatMissingData.NOT_BREACHING,
            ))

        # "The Average statistic represents the 4XXError error rate, namely, the total count of the 4XXError errors
        # divided by the total number of requests during the period."
        # https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-metrics-and-dimensions.html
        alarm_config = self.stack_inputs.api_gateway.http_4xx_error_alarm_config
        alarm_config.set_defaults(evaluation_periods=3, threshold=0.05)
        alarms.append(
            self._create_alarm(
                'ApiGateway4xxErrors',
                topic=self.warning_topic,
                description='Alarm if there are too many 4XX errors.',
                metric=api.metric_client_error(statistic='Average', period=DEFAULT_ALARM_PERIOD),
                evaluation_periods=alarm_config.evaluation_periods,
                threshold=alarm_config.threshold,
                treat_missing_data=TreatMissingData.NOT_BREACHING,
            ))

        return alarms

    def lambda_add_dlq_alarms(self, name: str, event_handler: Function, *,
                              dlq_send_error_alarm_config: AlarmConfigOverrides):
        """Adds alarms for a Lambda function that makes use of a dead-letter queue."""

        dlq_send_error_alarm_config.set_defaults(evaluation_periods=cast(int,
                                                                         Duration.hours(6).to_minutes()),
                                                 threshold=1)
        self._create_alarm(
            f'{name}DeadLetterErrors',
            topic=self.warning_topic,
            description='Alarm if events were attempted to be sent to the dead letter queue but failed.',
            metric=event_handler.metric(metric_name='DeadLetterErrors', statistic='Sum', period=DEFAULT_ALARM_PERIOD),
            evaluation_periods=dlq_send_error_alarm_config.evaluation_periods,
            threshold=dlq_send_error_alarm_config.threshold,
            datapoints_to_alarm=1,
            treat_missing_data=TreatMissingData.NOT_BREACHING,
        )

    def lambda_error_rate_alarm(self, event_handler: Alias, name: str, alarm_config: AlarmConfigOverrides) -> Alarm:
        """Creates an unmonitored alarm for a Lambda (either function or alias), watching for any errors."""

        _id = f'{name}FailedInvocations'

        # Only Alias generate a versioned metric and alarm, this is the weird of using Interfaces but
        # want a different behavior for each class, Alias -> versioned, Function -> Unversioned
        current_version_suffix: str
        handler_metric_error: IMetric
        handler_metric_invocations: IMetric

        handler_metric_error = cast(IMetric, event_handler.version.metric_errors(statistic='Sum', unit=Unit.COUNT))
        handler_metric_invocations = cast(IMetric,
                                          event_handler.version.metric_invocations(statistic='Sum', unit=Unit.COUNT))
        current_version_suffix = f'-{event_handler.version.version}'

        # Note that we will only calculate an error rate if there are enough invocations to make it meaningful
        assert alarm_config.minimum_invocations
        math_expression = cast(
            IMetric,
            MathExpression(
                expression=f'IF(total > {alarm_config.minimum_invocations}, (partial/total) * 100)',
                label='ErrorRatePct',
                period=DEFAULT_ALARM_PERIOD,
                using_metrics={
                    'partial': handler_metric_error,
                    'total': handler_metric_invocations,
                },
            ))

        # In production, add the region to the alarm name for ease of reading PagerDuty alerts
        if self.stack.stage == 'prod':
            alarm_name = f'{self.stack.stack_name}-{_id}-{self.stack.region}{current_version_suffix}'
        else:
            alarm_name = f'{self.stack.stack_name}-{_id}{current_version_suffix}'

        return Alarm(
            self,
            _id,
            alarm_name=alarm_name,
            alarm_description=self._get_alarm_description('Alarm if Lambda throws too many errors.'),
            metric=math_expression,
            evaluation_periods=cast(int, alarm_config.evaluation_periods),
            threshold=cast(float, alarm_config.threshold),
            comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=TreatMissingData.IGNORE,
        )

    def add_rest_lambda_function(self, function: Function):
        self._rest_lambdas.append(function)

    def lambda_rest_concurrency_alarm(self):
        """
        Generates a single alarm monitoring all concurrent executions for all REST Lambdas based on the API Gateway
        rate limit.
        """
        if not self._rest_lambdas:
            # No REST Lambdas defined
            return

        concurrent_execution_metrics = OrderedDict([(f'm{i + 1}',
                                                     cast(IMetric, f.metric('ConcurrentExecutions',
                                                                            statistic='Average')))
                                                    for i, f in enumerate(self._rest_lambdas)])

        self._create_alarm(
            'RestLambdasConcurrentExecutions',
            topic=self.warning_topic,
            description='REST Lambda concurrent executions are approaching API Gateway rate limits.',
            metric=MathExpression(label='SumOfConcurrentExecutions',
                                  expression=f'SUM([{", ".join(concurrent_execution_metrics.keys())}])',
                                  period=DEFAULT_ALARM_PERIOD,
                                  using_metrics=concurrent_execution_metrics),
            evaluation_periods=3,
            threshold=self.stack_inputs.api_gateway.throttling_burst_limit * 0.9,
            comparison_operator=ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=TreatMissingData.NOT_BREACHING,
        )

    def create_dashboard(self):
        """Adds our custom widgets to the CloudWatch dashboard."""

        # List of custom alarms
        if self._alarms:
            height = 1 + ceil(len(self._alarms) / 4)
            self.dashboard.add_widgets(AlarmStatusWidget(title='Alarms', alarms=self._alarms, height=height, width=24))

    def _create_alarm(self, _id: str, *, topic: Optional[Topic], description: str, **kwargs) -> Alarm:
        # In production, add the region to the alarm name for ease of reading PagerDuty alerts
        if self.stack.stage == 'prod':
            alarm_name = f'{self.stack.stack_name}-{_id}-{self.stack.region}'
        else:
            alarm_name = f'{self.stack.stack_name}-{_id}'

        alarm = Alarm(self,
                      _id,
                      alarm_name=alarm_name,
                      alarm_description=self._get_alarm_description(description),
                      **kwargs)

        self._add_alarm(alarm, topic=topic)
        return alarm

    def _add_alarm(self, alarm: AlarmBase, *, topic: Optional[Topic]) -> None:
        """
        A user-defined alarm will be activated, and PagerDuty notifications wired up if enabled.
        """
        if topic:
            action = cast(IAlarmAction, SnsAction(topic))
            alarm.add_alarm_action(action)
            alarm.add_ok_action(action)

        self._alarms.append(alarm)

    def _get_alarm_description(self, description: str) -> str:
        if not description:
            description = ''
        elif not description.endswith(' '):
            description += ' '
        return f'{description}See Runbook for more information: {self.stack_inputs.runbook_url}'
