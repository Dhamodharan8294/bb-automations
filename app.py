#!/usr/bin/env python

import os

import aws_cdk as cdk
from bb_fnds.cdk_constructs import pipeline_forge

from cdk.app_stack import AppStack
from cdk.core.stack_config import get_stack_inputs
from cdk.core.stack_inputs import PagerDutyOverrides


def main():
    app = cdk.App()

    for stack in pipeline_forge.Stack.from_env(app):
        stack_inputs = get_stack_inputs(stack)
        stack_inputs.tags = {
            tag.key: tag.value
            for tag in stack.raw_tags
        }

        if stack_inputs.developer_instance:
            stack_inputs.lambdas.blue_green_deployment = os.getenv('DEV_ENABLE_BLUE_GREEN') == '1'
            stack_inputs.lambdas.get_queues.only_saas_tenants = os.getenv('DEV_ONLY_SAAS_TENANTS') == '1'

            stack_inputs.alarms.pagerduty = PagerDutyOverrides(warning=os.getenv('DEV_WARNING_PAGER_DUTY'),
                                                               critical=os.getenv('DEV_CRITICAL_PAGER_DUTY'))

            if stack.is_il4:
                # Event forwarding between accounts is not allowed for IL4
                pass
            else:
                bridge = stack_inputs.eventbridge
                bridge.authz_permissions_event_bus_arn = os.getenv('DEV_AUTHZ_PERMISSIONS_EVENT_BUS_ARN')
                bridge.identity_provider_event_bus_arn = os.getenv('DEV_IDENTITY_PROVIDER_EVENT_BUS_ARN')
                bridge.platform_extensions_event_bus_arn = os.getenv('DEV_PLATFORM_EXTENSIONS_EVENT_BUS_ARN')
                bridge.achievements_inventory_event_bus_arn = os.getenv('DEV_ACHIEVEMENTS_INVENTORY_EVENT_BUS_ARN')
                bridge.achievements_rule_engine_event_bus_arn = os.getenv('DEV_ACHIEVEMENTS_RULE_ENGINE_EVENT_BUS_ARN')
                bridge.achievements_stud_record_event_bus_arn = os.getenv('DEV_ACHIEVEMENTS_STUD_RECORD_EVENT_BUS_ARN')
                bridge.learner_progression_student_alerts_event_bus_arn = os.getenv(
                    'DEV_LEARNER_PROGRESSION_STUDENT_ALERTS_EVENT_BUS_ARN')
                bridge.learner_progression_student_notes_event_bus_arn = os.getenv(
                    'DEV_LEARNER_PROGRESSION_STUDENT_NOTES_EVENT_BUS_ARN')

            stack_inputs.tests.enable_integ_rest_tests = stack_inputs.tests.enable_integ_rest_tests \
                                                         and os.getenv('DEV_DISABLE_DEPLOYMENT_TESTS') != '1'

        if stack_inputs.alarms.use_dashboard_suffix and not stack_inputs.alarms.dashboard_suffix:
            stack_inputs.alarms.dashboard_suffix = stack.region

        AppStack(stack, stack_inputs)

    app.synth()


if __name__ == "__main__":
    main()
