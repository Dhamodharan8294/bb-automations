from cdk.core.stack_inputs import AlarmOverrides, ApiGatewayOverrides, LambdaEventFunctionOverrides
from cdk.environments import PAGERDUTY_PROD
from cdk.stack_inputs import EventBridgeOverrides, EventHandlerOverrides, LambdasOverrides, StackInputs

config = StackInputs(
    alarms=AlarmOverrides(pagerduty=PAGERDUTY_PROD),
    api_gateway=ApiGatewayOverrides(
        throttling_rate_limit=10,
        throttling_burst_limit=5,
    ),
    eventbridge=EventBridgeOverrides(enable_archive=False),
    lambdas=LambdasOverrides(
        eventbridge_to_sqs=LambdaEventFunctionOverrides(reserved_concurrency=10),
        sqs_to_eventbridge=EventHandlerOverrides(reserved_concurrency=30),
        tenant_event_handler=EventHandlerOverrides(reserved_concurrency=5),
    ),
)
