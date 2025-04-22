from cdk.core.stack_inputs import AlarmConfigOverrides, AlarmOverrides, ApiGatewayOverrides, \
    LambdaEventFunctionOverrides, LambdaFunctionOverrides
from cdk.environments import PAGERDUTY_NON_PROD
from cdk.stack_inputs import EventHandlerOverrides, GetQueueFunctionOverrides, LambdasOverrides, \
    StackInputs

config = StackInputs(
    alarms=AlarmOverrides(
        pagerduty=PAGERDUTY_NON_PROD,
        use_dashboard_suffix=False,
    ),
    api_gateway=ApiGatewayOverrides(
        latency_alarm_config=AlarmConfigOverrides(threshold=1500),
        throttling_rate_limit=10,
        throttling_burst_limit=5,
    ),
    lambdas=LambdasOverrides(
        get_queue=GetQueueFunctionOverrides(only_saas_tenants=False),
        eventbridge_to_sqs=LambdaEventFunctionOverrides(reserved_concurrency=75),
        sqs_to_eventbridge=EventHandlerOverrides(reserved_concurrency=100),
        tenant_event_handler=EventHandlerOverrides(reserved_concurrency=15),
        tenant_resources_get_stack_status=LambdaFunctionOverrides(reserved_concurrency=5),
        tenant_resources_manage_metadata=LambdaFunctionOverrides(reserved_concurrency=5),
    ),
)
