from cdk.core.stack_inputs import AlarmConfigOverrides, AlarmOverrides, ApiGatewayOverrides
from cdk.stack_inputs import GetQueueFunctionOverrides, LambdasOverrides, StackInputs

config = StackInputs(
    alarms=AlarmOverrides(),
    api_gateway=ApiGatewayOverrides(
        latency_alarm_config=AlarmConfigOverrides(threshold=1500),
        throttling_rate_limit=10,
        throttling_burst_limit=5,
    ),
    lambdas=LambdasOverrides(
        blue_green_deployment=False,
        log_level="INFO",
        get_queue=GetQueueFunctionOverrides(only_saas_tenants=False),
    ),
)
