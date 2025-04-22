from cdk.core.stack_inputs import AlarmConfigOverrides, AlarmOverrides, ApiGatewayOverrides, \
    LambdaEventFunctionOverrides
from cdk.environments import PAGERDUTY_PROD
from cdk.stack_inputs import EventBridgeOverrides, EventHandlerOverrides, GetQueueFunctionOverrides, LambdasOverrides, \
    StackInputs

config = StackInputs(
    alarms=AlarmOverrides(pagerduty=PAGERDUTY_PROD),
    api_gateway=ApiGatewayOverrides(
        latency_alarm_config=AlarmConfigOverrides(threshold=1500),
        throttling_rate_limit=10,
        throttling_burst_limit=5,
    ),
    lambdas=LambdasOverrides(
        get_queue=GetQueueFunctionOverrides(skip_tenant_api_errors=True),
        eventbridge_to_sqs=LambdaEventFunctionOverrides(reserved_concurrency=75),
        sqs_to_eventbridge=EventHandlerOverrides(reserved_concurrency=100),
        tenant_event_handler=EventHandlerOverrides(reserved_concurrency=5),
    ),

    # Event Bridge archive is not supported in govcloud
    eventbridge=EventBridgeOverrides(enable_archive=False),
)
