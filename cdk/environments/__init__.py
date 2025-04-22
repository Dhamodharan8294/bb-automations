from cdk.core.stack_inputs import PagerDutyOverrides

PAGERDUTY_PROD = PagerDutyOverrides(
    warning="https://events.pagerduty.com/integration/fcd1d5c0b28b4d379638b9d63142a350/enqueue",
    critical="https://events.pagerduty.com/integration/1e4f8b580e8d4ece825214308e6e2be3/enqueue",
)

PAGERDUTY_NON_PROD = PagerDutyOverrides(
    warning="https://events.pagerduty.com/integration/ee3e87ccaeeb4fc3bd79768f279fae34/enqueue",
    critical="https://events.pagerduty.com/integration/81266325cd5e43059b20c6656b4fec87/enqueue",
)
