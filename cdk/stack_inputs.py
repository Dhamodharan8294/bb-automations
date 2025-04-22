from dataclasses import dataclass, field
from typing import Optional

from cdk.core.stack_inputs import CoreLambdasOverrides, CoreStackInputs, LambdaEventFunctionOverrides, \
    LambdaFunctionOverrides


@dataclass
class GetQueueFunctionOverrides(LambdaFunctionOverrides):
    only_saas_tenants: bool = True
    skip_tenant_api_errors: bool = False


@dataclass
class EventHandlerOverrides(LambdaEventFunctionOverrides):
    # Visibility timeout should be set in conjunction with LambdaEventFunctionOverrides.timeout_seconds
    # AWS documentation suggests that this value be at least six times the Lambda timeout value.
    # Reference: https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html
    queue_visibility_timeout_seconds: Optional[int] = None


@dataclass
class LambdasOverrides(CoreLambdasOverrides):
    # Default logging-level
    log_level: str = "WARNING"

    # Function-specific overrides
    get_queue: GetQueueFunctionOverrides = field(default_factory=GetQueueFunctionOverrides)
    get_queues: LambdaFunctionOverrides = field(default_factory=LambdaFunctionOverrides)
    delete_queues: LambdaFunctionOverrides = field(default_factory=LambdaFunctionOverrides)
    eventbridge_to_sqs: LambdaEventFunctionOverrides = field(default_factory=LambdaEventFunctionOverrides)
    sqs_to_eventbridge: EventHandlerOverrides = field(default_factory=EventHandlerOverrides)
    tenant_event_handler: EventHandlerOverrides = field(default_factory=EventHandlerOverrides)
    tenant_resources_deploy_stack: LambdaFunctionOverrides = field(default_factory=LambdaFunctionOverrides)
    tenant_resources_destroy_stack: LambdaFunctionOverrides = field(default_factory=LambdaFunctionOverrides)
    tenant_resources_get_stack_status: LambdaFunctionOverrides = field(default_factory=LambdaFunctionOverrides)
    tenant_resources_manage_metadata: LambdaFunctionOverrides = field(default_factory=LambdaFunctionOverrides)


@dataclass
class TestOverrides:
    enable_integ_rest_tests: bool = False


@dataclass
class EventBridgeOverrides:
    authz_permissions_event_bus_arn: Optional[str] = None
    identity_provider_event_bus_arn: Optional[str] = None
    platform_extensions_event_bus_arn: Optional[str] = None
    achievements_inventory_event_bus_arn: Optional[str] = None
    achievements_rule_engine_event_bus_arn: Optional[str] = None
    achievements_stud_record_event_bus_arn: Optional[str] = None
    learner_progression_student_alerts_event_bus_arn: Optional[str] = None
    learner_progression_student_notes_event_bus_arn: Optional[str] = None

    enable_archive: bool = True


@dataclass
class StackInputs(CoreStackInputs):
    lambdas: LambdasOverrides = field(default_factory=LambdasOverrides)

    eventbridge: EventBridgeOverrides = field(default_factory=EventBridgeOverrides)
    tests: TestOverrides = field(default_factory=TestOverrides)

    runbook_url: str = 'https://confluence.bbpd.io/display/PLAT/Foundations+Connector+Runbook'
