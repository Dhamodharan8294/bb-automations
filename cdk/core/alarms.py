from aws_cdk import Duration, aws_dynamodb, aws_lambda, aws_sqs
from bb_fnds.cdk_constructs import monitoring as m, pipeline_forge

from cdk.core.cloudwatch import CloudWatch
from cdk.core.stack_inputs import CoreStackInputs, LambdaAlarmOverrides, SQSAlarmOverrides

# cdk-constructs defaults to 1 evaluation period of 10 minutes; replace that with multiple smaller periods to
# reduce odds of flaky alarms.
ALARM_PERIOD = Duration.minutes(1)
ALARM_EVALUATION_PERIODS = 3


class Alarms:
    monitor: m.Monitor

    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: CoreStackInputs, cloudwatch: CloudWatch):
        self.stack = stack
        self.stack_inputs = stack_inputs

        self.monitor = m.Monitor(stack,
                                 "Monitor",
                                 cloudwatch_dashboard=cloudwatch.dashboard,
                                 warning_alarms_sns_topic=cloudwatch.warning_topic,
                                 warning_alarms_pager_duty_url=stack_inputs.alarms.pagerduty.warning,
                                 critical_alarms_sns_topic=cloudwatch.critical_topic,
                                 critical_alarms_pager_duty_url=stack_inputs.alarms.pagerduty.critical)

        dynamodb_ops = [
            aws_dynamodb.Operation.BATCH_GET_ITEM,
            aws_dynamodb.Operation.DELETE_ITEM,
            aws_dynamodb.Operation.GET_ITEM,
            aws_dynamodb.Operation.PUT_ITEM,
            aws_dynamodb.Operation.QUERY,
            aws_dynamodb.Operation.UPDATE_ITEM,
            aws_dynamodb.Operation.TRANSACT_WRITE_ITEMS,
        ]
        dynamo_request_latency_config = stack_inputs.dynamodb.latency_alarm_config
        dynamo_request_latency_config.set_defaults(evaluation_periods=3, threshold=200)
        dynamo_system_error_rate_config = stack_inputs.dynamodb.error_rate_alarm_config
        dynamo_system_error_rate_config.set_defaults(evaluation_periods=2, threshold=2)

        self.monitor.watch_scope(
            stack,
            api_gateway_options=m.ApiGatewayMonitorOptions(
                availability_critical_props=m.ApiGatewayAvailabilityAlarmProps(
                    runbook_url=stack_inputs.runbook_url,
                    slo=stack_inputs.alarms.slo_availability,
                    period=ALARM_PERIOD,
                    evaluation_periods=ALARM_EVALUATION_PERIODS,
                )),
            dynamo_options=m.DynamoMonitorOptions(
                high_request_latency_critical_props=[
                    m.DynamoLatencyOperationAlarmProps(
                        operation=op,
                        props=m.OptionalDynamoAlarmProps(
                            runbook_url=stack_inputs.runbook_url,
                            threshold=dynamo_request_latency_config.threshold,
                            period=ALARM_PERIOD,
                            evaluation_periods=dynamo_request_latency_config.evaluation_periods,
                        ),
                    ) for op in dynamodb_ops
                ],
                system_error_rate_critical_props=m.OptionalDynamoAlarmProps(
                    runbook_url=stack_inputs.runbook_url,
                    threshold=dynamo_system_error_rate_config.threshold,
                    period=ALARM_PERIOD,
                    evaluation_periods=dynamo_system_error_rate_config.evaluation_periods,
                ),
                system_errors_alarm_operations=dynamodb_ops,
            ),
            event_bridge_options=m.EventBridgeMonitorOptions(
                failed_invocations_critical_props=m.EventBridgeFailedInvocationsAlarmProps(
                    runbook_url=stack_inputs.runbook_url,
                    threshold=0,
                ),
                throttle_critical_props=m.EventBridgeThrottleAlarmProps(
                    runbook_url=stack_inputs.runbook_url,
                    evaluation_periods=ALARM_EVALUATION_PERIODS,
                ),
                # We don't enable DLQs with EventBridge
                dlq_critical_enabled=False,
                failed_dlq_critical_enabled=False,
            ),
            sfn_state_machine_options=m.SfnStateMachineMonitorOptions(
                api_quota_usage_critical_enabled=False,
                api_throttling_critical_enabled=False,
                service_quota_usage_critical_enabled=False,
                service_throttling_critical_enabled=False,
                state_machine_availability_critical_props=m.SfnStateMachineAvailabilityAlarmProps(
                    slo=stack_inputs.alarms.slo_availability,
                    runbook_url=stack_inputs.runbook_url,
                    period=ALARM_PERIOD,
                    evaluation_periods=ALARM_EVALUATION_PERIODS,
                ),
            ),
        )

        # Ignore resources that are part of monitoring itself
        if cloudwatch.warning_topic:
            self.monitor.ignore(cloudwatch.warning_topic)
        if cloudwatch.critical_topic:
            self.monitor.ignore(cloudwatch.critical_topic)

    def monitor_sqs_queue(self, queue: aws_sqs.Queue, overrides: SQSAlarmOverrides):
        if overrides.message_age_threshold:
            message_age_threshold = overrides.message_age_threshold.to_seconds()
        else:
            message_age_threshold = None

        self.monitor.watch_sqs_queue(
            queue,
            inflight_messages_alarm_enabled=False,
            visible_messages_alarm_enabled=overrides.visible_messages_enabled,
            visible_messages_alarm_props=m.SqsVisibleMessagesAlarmProps(
                runbook_url=self.stack_inputs.runbook_url,
                threshold=overrides.visible_messages_threshold,
                evaluation_periods=overrides.visible_messages_evaluation_periods,
            ),
            oldest_messages_alarm_enabled=overrides.message_age_enabled,
            oldest_messages_alarm_props=m.SqsOldestMessagesAlarmProps(
                runbook_url=self.stack_inputs.runbook_url,
                threshold=message_age_threshold,
                period=overrides.message_age_periods,
                evaluation_periods=overrides.message_age_evaluation_periods,
            ),
        )

    def monitor_lambda(self, function: aws_lambda.Function, overrides: LambdaAlarmOverrides):
        runbook_url = self.stack_inputs.runbook_url
        self.monitor.watch_lambda_function(
            function,
            availability_critical_enabled=overrides.availability_enabled,
            availability_critical_props=m.LambdaAvailabilityAlarmProps(
                runbook_url=runbook_url,
                slo=self.stack_inputs.alarms.slo_availability,
                period=ALARM_PERIOD,
                evaluation_periods=5,
            ),
            concurrency_utilization_warning_enabled=False,
            duration_critical_enabled=False,
            duration_warning_enabled=overrides.duration_enabled,
            duration_warning_props=m.LambdaDurationOptionalAlarmProps(
                runbook_url=runbook_url,
                period=ALARM_PERIOD,
                evaluation_periods=ALARM_EVALUATION_PERIODS,
                # Alarm is monitoring _average_ duration. If the average is taking this
                # long then we likely have a number of executions that are timing out.
                timeout_percentage_threshold=50,
            ),
            throttle_critical_enabled=overrides.throttling_enabled,
            throttle_critical_props=m.LambdaThrottleAlarmProps(
                runbook_url=runbook_url,
                evaluation_periods=overrides.throttling_evaluation_periods,
            ),
            dashboard_properties=m.LambdaDashboardProps(
                concurrency_enabled=True,
                duration_enabled=overrides.duration_enabled,
                error_rate_enabled=True,
                invocations_enabled=True,
                iterator_age_enabled=True,
                throttles_enabled=True,
            ),
        )
