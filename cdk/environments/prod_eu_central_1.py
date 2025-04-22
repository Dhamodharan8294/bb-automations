from cdk.core.stack_inputs import AlarmConfigOverrides, AlarmOverrides, ApiGatewayOverrides, \
    LambdaEventFunctionOverrides
from cdk.environments import PAGERDUTY_PROD
from cdk.stack_inputs import EventHandlerOverrides, LambdasOverrides, StackInputs

config = StackInputs(
    alarms=AlarmOverrides(pagerduty=PAGERDUTY_PROD),
    api_gateway=ApiGatewayOverrides(
        latency_alarm_config=AlarmConfigOverrides(threshold=700),
        throttling_rate_limit=20,
        throttling_burst_limit=10,
    ),
    lambdas=LambdasOverrides(
        eventbridge_to_sqs=LambdaEventFunctionOverrides(reserved_concurrency=150),
        sqs_to_eventbridge=EventHandlerOverrides(reserved_concurrency=200),
        tenant_event_handler=EventHandlerOverrides(reserved_concurrency=5),
    ),
)
