from dataclasses import dataclass, field
from typing import Optional

from aws_cdk import Duration
from bb_ent_data_services_shared.cdk.stack_inputs import DynamoDbOverrides


@dataclass
class PagerDutyOverrides:
    critical: Optional[str] = None
    warning: Optional[str] = None


@dataclass
class AlarmOverrides:
    pagerduty: PagerDutyOverrides = field(default_factory=PagerDutyOverrides)
    use_dashboard_suffix: bool = True
    dashboard_suffix: Optional[str] = None
    slo_availability: float = 99.9


@dataclass
class AlarmConfigOverrides:
    threshold: Optional[float] = None
    evaluation_periods: Optional[int] = None
    minimum_invocations: Optional[int] = None

    def set_defaults(self,
                     *,
                     threshold: Optional[float] = None,
                     evaluation_periods: Optional[int] = None,
                     minimum_invocations: Optional[int] = None):
        if self.threshold is None:
            self.threshold = threshold
        if self.evaluation_periods is None:
            self.evaluation_periods = evaluation_periods
        if self.minimum_invocations is None:
            self.minimum_invocations = minimum_invocations


@dataclass
class ApiGatewayOverrides:
    latency_alarm_config: AlarmConfigOverrides = field(default_factory=AlarmConfigOverrides)
    http_4xx_error_alarm_config: AlarmConfigOverrides = field(default_factory=AlarmConfigOverrides)
    # average requests per second to allow (across all endpoints)
    throttling_rate_limit: Optional[int] = None
    # maximum concurrency to allow (across all endpoints)
    throttling_burst_limit: Optional[int] = None


@dataclass
class SQSAlarmOverrides:
    # Whether to enable the visible messages alarm
    visible_messages_enabled: bool = True
    # Maximum number of unprocessed messages in the queue
    visible_messages_threshold: Optional[int] = None
    # Number of 5-minute periods before alerting on violation
    visible_messages_evaluation_periods: Optional[int] = None
    # Whether to alert based on the age of the oldest message in the queue
    message_age_enabled: bool = True
    # Maximum age of unprocessed messages in the queue
    message_age_threshold: Optional[Duration] = None
    # The length of time to watch the metric for
    message_age_periods: Optional[Duration] = None
    # Number of message_age_periods intervals before alerting on violation
    message_age_evaluation_periods: Optional[int] = None

    def set_lambda_event_source_defaults(self,
                                         *,
                                         message_age_threshold: Duration = Duration.hours(3),
                                         message_age_periods: Optional[Duration] = Duration.minutes(10),
                                         message_age_evaluation_periods: int = 6):
        """Sets defaults for a queue being used as a Lambda event source"""
        if self.message_age_threshold is None:
            self.message_age_threshold = message_age_threshold
        if self.message_age_periods is None:
            self.message_age_periods = message_age_periods
        if self.message_age_evaluation_periods is None:
            self.message_age_evaluation_periods = message_age_evaluation_periods
        self.visible_messages_enabled = False

    def set_dlq_defaults(self):
        """Sets defaults for a DLQ"""
        if self.visible_messages_threshold is None:
            self.visible_messages_threshold = 0
        if self.visible_messages_evaluation_periods is None:
            self.visible_messages_evaluation_periods = 3
        self.message_age_enabled = False


@dataclass
class LambdaAlarmOverrides:
    # Whether to enable the availability alarm
    availability_enabled: Optional[bool] = None
    # Whether to enable the duration alarm
    duration_enabled: Optional[bool] = None
    # Whether to enable the throttling alarm
    throttling_enabled: Optional[bool] = None
    # Evaluation periods for throttling alarm (default: let cdk-constructs choose)
    throttling_evaluation_periods: Optional[int] = None

    def set_defaults(
        self,
        availability_enabled: bool = True,
        duration_enabled: bool = True,
        throttling_enabled: bool = True,
    ):
        if self.availability_enabled is None:
            self.availability_enabled = availability_enabled
        if self.duration_enabled is None:
            self.duration_enabled = duration_enabled
        if self.throttling_enabled is None:
            self.throttling_enabled = throttling_enabled


@dataclass
class LambdaFunctionOverrides:
    timeout_seconds: Optional[int] = None
    deployment_group_error_rate_alarm_config: AlarmConfigOverrides = field(default_factory=AlarmConfigOverrides)
    reserved_concurrency: Optional[int] = None
    # Alarm configuration for the Lambda
    alarms: LambdaAlarmOverrides = field(default_factory=LambdaAlarmOverrides)


@dataclass
class LambdaEventFunctionOverrides(LambdaFunctionOverrides):
    dlq_send_error_alarm_config: AlarmConfigOverrides = field(default_factory=AlarmConfigOverrides)
    recurring_errors_alarm_config: AlarmConfigOverrides = field(default_factory=AlarmConfigOverrides)
    # Alarm configuration for the SQS queue events are consumed from
    queue_alarm: SQSAlarmOverrides = field(default_factory=SQSAlarmOverrides)
    # Alarm configuration for the SQS queue failed events are sent to
    dlq_alarm: SQSAlarmOverrides = field(default_factory=SQSAlarmOverrides)

    def set_sqs_alarm_defaults(self, *, message_age_threshold: Duration = Duration.hours(3)):
        self.queue_alarm.set_lambda_event_source_defaults(message_age_threshold=message_age_threshold)
        self.dlq_alarm.set_dlq_defaults()


@dataclass
class CoreLambdasOverrides:
    blue_green_deployment: bool = True


@dataclass
class CoreStackInputs:
    runbook_url: str

    developer_instance: bool = False
    tags: dict[str, str] = field(default_factory=lambda: {})
    alarms: AlarmOverrides = field(default_factory=AlarmOverrides)
    api_gateway: ApiGatewayOverrides = field(default_factory=ApiGatewayOverrides)
    dynamodb: DynamoDbOverrides = field(default_factory=DynamoDbOverrides)
