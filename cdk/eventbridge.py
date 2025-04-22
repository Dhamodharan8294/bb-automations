import re
from dataclasses import dataclass
from typing import Optional

import constructs
from aws_cdk import Annotations, CfnOutput, Duration
from aws_cdk.aws_events import EventBus, EventPattern, IEventBus, Rule
from aws_cdk.aws_events_targets import EventBus as EventBusTarget
from bb_fnds.cdk_constructs import event_hub, pipeline_forge

from cdk.core.cloudwatch import CloudWatch
from cdk.core.eventbridge import Eventbridge as CoreEventbridge
from cdk.stack_inputs import StackInputs


@dataclass(init=False)
class Eventbridge(CoreEventbridge):
    private_event_bus: event_hub.EventBus
    enterprise_objects_bus: event_hub.EventBus
    learn_rule_subscriptions: list[Rule]
    events_ignore_missing_tenants: dict[str, list[str]]

    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: StackInputs, cloudwatch: CloudWatch):
        super().__init__(stack, stack_inputs)
        self.cloudwatch = cloudwatch

        # Private bus for our own event subscriptions
        self.private_event_bus = self._create_private_event_bus()

        # Shared bus for enterprise data services. All events received from Learn will be put onto this bus, and our
        # downstream services will use this same bus to send events back to Learn.
        self.enterprise_objects_bus = self._create_enterprise_objects_bus()

        # Event subscriptions that should be forwarded to Learn
        self.learn_rule_subscriptions = []

        # Add event sources and a list of their detail types to tell our delivery Lambda that it's okay to ignore
        # events of this type that go to a tenant which no longer exists.
        self.events_ignore_missing_tenants = {}

        # Custom scope to contain forwarding rules
        self.forwarding_scope = constructs.Construct(self.stack, 'Eventbridge')

        # Forward events between Learn and Foundations services
        self._integrate_enterprise_data_services()
        self._integrate_authz_permissions_service()
        self._integrate_feature_flags_service()
        self._integrate_identity_provider_service()
        self._integrate_platform_extensions_service()
        self._integrate_achievements_service()
        self._integrate_learner_progression_service()

    def _create_private_event_bus(self) -> event_hub.EventBus:
        return event_hub.EventBus(self.stack, 'PrivateEventBus', event_bus_name=self.stack.stack_name)

    def _create_enterprise_objects_bus(self) -> event_hub.EventBus:
        bus_name = f'enterprise-objects-bus-{self.stack.stage}'
        if self.stack.deployment:
            bus_name += f'-{self.stack.deployment}'

        # Create an EventHub-enabled bus
        event_bus = event_hub.EventBus(self.stack, 'EnterpriseObjectsBus', event_bus_name=bus_name)

        if self.stack_inputs.eventbridge.enable_archive:
            # Archive enterprise events so they can be replayed when new services come online
            # Note: Prefix matching not supported yet by CDK: https://github.com/aws/aws-cdk/issues/6184
            if self.stack.stage == 'prod':
                # Retain production events forever
                archive_retention = None
            else:
                # Discard non-prod events after a week
                archive_retention = Duration.days(7)
            event_bus.archive('Archive',
                              event_pattern=EventPattern(source=[
                                  'bb.authz.permissions',
                                  'bb.enterprise.course',
                                  'bb.enterprise.course.membership',
                                  'bb.enterprise.data.source',
                                  'bb.enterprise.institutional.hierarchy',
                                  'bb.enterprise.term',
                                  'bb.enterprise.user',
                              ]),
                              archive_name=bus_name,
                              retention=archive_retention)

        CfnOutput(self.stack,
                  'EnterpriseObjectsBusArn',
                  value=event_bus.event_bus_arn,
                  description='The ARN of the Enterprise Objects event bus',
                  export_name=bus_name)

        return event_bus

    def _integrate_enterprise_data_services(self):
        # Our own services publish to our shared enterprise_object_bus, so no EventHub subscription is required
        services = {
            'Course': 'bb.enterprise.course',
            'CourseMembership': 'bb.enterprise.course.membership',
            'DataSource': 'bb.enterprise.data.source',
            'InstHierarchy': 'bb.enterprise.institutional.hierarchy',
            'Term': 'bb.enterprise.term',
            'User': 'bb.enterprise.user',
        }
        for label, source in services.items():
            rule = Rule(self.stack,
                        f'Enterprise{label}EventsRule',
                        event_bus=self.enterprise_objects_bus,
                        event_pattern=EventPattern(source=[source]))
            self.learn_rule_subscriptions += [rule]

    def _integrate_authz_permissions_service(self):
        # https://github.com/blackboard-foundations/bb-authz-permissions/blob/main/docs/EVENTS-CONSUMED.md
        self._create_forwarding_rules(
            dev_bus_arns={
                'AuthzPermissions': self.stack_inputs.eventbridge.authz_permissions_event_bus_arn,
            },
            events={
                'learn.role': [
                    'Role Created',
                    'Role Updated',
                    'Role Deleted',
                ],
                'learn.entitlement': [
                    'Entitlement Created',
                    'Entitlement Updated',
                    'Entitlement Deleted',
                ],
                'learn.role.entitlement': [
                    'Entitlement Added to Role',
                    'Entitlement Deleted from Role',
                ],
            },
        )

        # https://github.com/blackboard-foundations/bb-authz-permissions/blob/main/docs/EVENTS-PRODUCED.md
        self._create_authz_permissions_subscription('AuthzEntitlementCreated', detail_type='Entitlement Created')
        self._create_authz_permissions_subscription('AuthzEntitlementUpdated', detail_type='Entitlement Updated')
        self._create_authz_permissions_subscription('AuthzEntitlementDeleted', detail_type='Entitlement Deleted')

        self._create_authz_permissions_subscription('AuthzRoleCreated', detail_type='Role Created')
        self._create_authz_permissions_subscription('AuthzRoleUpdated', detail_type='Role Updated')
        self._create_authz_permissions_subscription('AuthzRoleDeleted', detail_type='Role Deleted')

        self._create_authz_permissions_subscription('AuthzRoleEntitlementCreated',
                                                    detail_type='Entitlement Added to Role')
        self._create_authz_permissions_subscription('AuthzRoleEntitlementDeleted',
                                                    detail_type='Entitlement Deleted from Role')

        # Combine subscriptions above into a single rule for our Lambda
        rule = Rule(self.stack,
                    'PermissionsEventsRule',
                    event_bus=self.enterprise_objects_bus,
                    event_pattern=EventPattern(source=["bb.authz.permissions"]))
        self.learn_rule_subscriptions += [rule]

    def _create_authz_permissions_subscription(self, _id, *, detail_type: str):
        # Subscribe to events for non-developer instances and allow local-stage developer instances to target the
        # dummy EventHub endpoints
        event_hub.Subscription(
            self.stack,
            _id,
            source='bb.authz.permissions',
            target_event_bus=self.enterprise_objects_bus,
            detail_type=detail_type,
            omit_rule=True,  # We'll create a single combined rule to send all events to the Lambda
        )

    def _integrate_feature_flags_service(self):
        # https://github.com/blackboard-foundations/bb-feature-flags/blob/master/docs/EVENTS-PRODUCED.md
        source = 'bb.feature.flags'
        self._create_feature_flags_subscription('FeatureFlagDefinitionDeleted',
                                                source=source,
                                                detail_type='Feature Flag Definition Deleted')
        self._create_feature_flags_subscription('FeatureFlagValueChanged',
                                                source=source,
                                                detail_type='Feature Flag Value Changed')
        self._create_feature_flags_subscription('FeatureFlagValueDeleted',
                                                source=source,
                                                detail_type='Feature Flag Value Deleted')

        # Combine subscriptions above into a single rule for our Lambda
        rule = Rule(self.stack,
                    'FeatureFlagsEventsRule',
                    event_bus=self.enterprise_objects_bus,
                    event_pattern=EventPattern(source=[source]))
        self.learn_rule_subscriptions += [rule]

    def _create_feature_flags_subscription(self, _id, *, source: str, detail_type: str):
        # No need to throw an error if feature-flag broadcast events go to a tenant that no longer exists
        self.events_ignore_missing_tenants[source] = [detail_type]

        # Subscribe to events for non-developer instances and allow local-stage developer instances to target the
        # dummy EventHub endpoints
        event_hub.Subscription(
            self.stack,
            _id,
            source=source,
            target_event_bus=self.enterprise_objects_bus,
            detail_type=detail_type,
            omit_rule=True,  # We'll create a single combined rule to send all events to the Lambda
        )

    def _integrate_identity_provider_service(self):
        # https://github.com/blackboard-foundations/bb-auth-broker-provisioner/blob/main/docs/EVENTS-CONSUMED.md
        self._create_forwarding_rules(
            dev_bus_arns={
                'IdentityProvider': self.stack_inputs.eventbridge.identity_provider_event_bus_arn,
            },
            events={
                'bb.learn.foundations.auth': [
                    'SyncLearnHosts',
                    'SyncRestrictedHosts',
                    'ProvisionLC',
                ],
            },
        )

        # https://github.com/blackboard-foundations/bb-auth-broker-provisioner/blob/main/docs/EVENTS-PRODUCED.md
        # TODO: bb-auth-broker-provisioner currently publishes directly to our bus; it should use EventHub
        rule = Rule(self.stack,
                    'AuthBrokerProvisionerEventsRule',
                    event_bus=self.enterprise_objects_bus,
                    event_pattern=EventPattern(source=["bb.auth.broker.provisioner"]))
        self.learn_rule_subscriptions += [rule]

    def _integrate_platform_extensions_service(self):
        # https://github.com/blackboard-foundations/bb-platform-extensions-biz-rules/blob/main/definitions/events.ts
        self._create_forwarding_rules(
            dev_bus_arns={
                'PlatformExtensions': self.stack_inputs.eventbridge.platform_extensions_event_bus_arn,
            },
            events={
                'bb.learn.platform.extensions': [
                    'GradeEventsFromLearn',
                ]
            },
        )

    def _integrate_achievements_service(self):
        # https://github.com/blackboard-foundations/bb-achievements-rule-engine/blob/main/docs/events.md#events-consumed
        self._create_forwarding_rules(
            scope=constructs.Construct(self.forwarding_scope, 'Achievements'),
            dev_bus_arns={
                'AchievementsRuleEngine': self.stack_inputs.eventbridge.achievements_rule_engine_event_bus_arn,
            },
            events={
                'learn.grading': [
                    'Grade Changed',
                ],
            },
            dev_events={
                'bb.enterprise.course.membership': [
                    'Membership Deleted',
                ],
            })

        # https://github.com/blackboard-foundations/bb-achievements-inventory/blob/main/docs/events.md#events-consumed
        self._create_forwarding_rules(
            scope=constructs.Construct(self.forwarding_scope, 'AchievementsInventory'),
            dev_bus_arns={
                'AchievementsInventory': self.stack_inputs.eventbridge.achievements_inventory_event_bus_arn,
            },
            events={},
            dev_events={
                'bb.enterprise.course': [
                    'Course Deleted',
                ],
                'bb.enterprise.course.membership': [
                    'Membership Deleted',
                ],
            })

        # https://github.com/blackboard-foundations/bb-achievements-student-record/blob/main/docs/events.md#events-consumed
        self._create_forwarding_rules(
            scope=constructs.Construct(self.forwarding_scope, 'AchievementsStudentRecord'),
            dev_bus_arns={
                'AchievementsStudentRecord': self.stack_inputs.eventbridge.achievements_stud_record_event_bus_arn,
            },
            events={},
            dev_events={
                'bb.enterprise.course': [
                    'Course Deleted',
                ],
                'bb.enterprise.course.membership': [
                    'Membership Deleted',
                ],
            })

        inventory_source = 'achievements.inventory'
        # Subscribe to the event described in
        # https://github.com/blackboard-foundations/bb-achievements-inventory/blob/main/docs/events.md#achievement-published-count
        subscription = self._create_achievements_subscription('AchievementPublishedCount',
                                                              source=inventory_source,
                                                              detail_type='Achievement Published Count')

        self.learn_rule_subscriptions += [subscription.rule]

    def _create_achievements_subscription(self, _id, *, source: str, detail_type: str):
        # Subscribe to events for non-developer instances and allow local-stage developer instances to target the
        # dummy EventHub endpoints
        return event_hub.Subscription(self.stack,
                                      _id,
                                      source=source,
                                      target_event_bus=self.enterprise_objects_bus,
                                      detail_type=detail_type)

    def _integrate_learner_progression_service(self):
        self._create_forwarding_rules(
            scope=constructs.Construct(self.forwarding_scope, 'LearnerProgression'),
            dev_bus_arns={
                'StudentAlerts': self.stack_inputs.eventbridge.learner_progression_student_alerts_event_bus_arn,
                'StudentNotes': self.stack_inputs.eventbridge.learner_progression_student_notes_event_bus_arn,
            },
            events={
                'learn.learner.progression': [
                    'Student Alerts Created',
                    'Student Note Created',
                    'Student Note Modified',
                    'Student Note Deleted',
                ],
            })

    def _create_forwarding_rules(self,
                                 *,
                                 dev_bus_arns: Optional[dict[str, Optional[str]]] = None,
                                 events: dict[str, list[str]],
                                 dev_events: Optional[dict[str, list[str]]] = None,
                                 scope: Optional[constructs.Construct] = None):
        """
        Configures EventBridge to forward events from our enterprise-objects-bus to the downstream service.

        Originally we created cross-account forwarding rules manually, but we are moving towards always using EventHub
        for this. Once the remaining services have been updated to register EventHub subscriptions, the only time we
        will create forwarding rules ourselves if for developer deployments (which EventHub does not support).

        :param dev_bus_arns: One or more EventBridge buses to forward events to. May only be used for developer local
                             stacks. Production stacks must use EventHub.
        :param events: Dictionary of event sources and the associated detail types that should be forwarded.
        :param dev_events: Extra events that will only be forwarded if bus_arn is set.
        """
        if not scope:
            # Existing resources cannot have their parent scope changed. New resources should include a scope to make
            # the CloudFormation Tree View more useful.
            scope = self.stack

        if dev_bus_arns:
            for bus_id, bus_arn in dev_bus_arns.items():
                if not bus_arn:
                    continue

                if not self.stack_inputs.developer_instance:
                    Annotations.of(
                        self.stack).add_error(message='Only local stacks may use manually configured forwarding rules')
                    return

                # Manually build relationship between our bus and the other service's bus
                target_event_bus = EventBus.from_event_bus_arn(scope, bus_id, event_bus_arn=bus_arn)
                if not self._is_local_bus(target_event_bus):
                    Annotations.of(self.stack).add_error(
                        message='Misconfigured developer tunable: Local deploys may not use the shared event bus ' +
                        target_event_bus.event_bus_name)
                    return

                # Forward Learn events to target event bus
                rule_id = f'{bus_id}Forwarder'
                rule_name = f'{self.stack.stack_name}-{rule_id}'
                event_sources = list(events.keys())
                if dev_events:
                    event_sources.extend(dev_events.keys())
                rule = Rule(scope,
                            rule_id,
                            event_bus=self.enterprise_objects_bus,
                            event_pattern=EventPattern(source=event_sources,
                                                       detail={
                                                           "tenantId": [{
                                                               "anything-but": {
                                                                   "prefix": "bb.test-tenant-id"
                                                               }
                                                           }]
                                                       }),
                            rule_name=rule_name)
                rule.add_target(target=EventBusTarget(target_event_bus))

        if not events:
            # This is a dev-only forwarder
            return

        if events:
            # Declare simple event schemas for the events sent from Learn. If the real schemas are needed in the
            # future, projects using fnds-connector to forward events will need to provide schemas as part of their
            # integration.
            schema_content = """{
              "openapi": "3.0.0",
              "info": {
                "version": "1.0.0",
                "title": "Undocumented event"
              },
              "paths": {}
            }
            """

            for source, detail_types in events.items():
                source_scope = constructs.Construct(self.forwarding_scope, source.title().replace('.', ''))
                for detail_type in detail_types:
                    schema_id = detail_type.title().replace(' ', '')
                    event_hub.Schema(source_scope,
                                     schema_id,
                                     source_event_bus=self.enterprise_objects_bus,
                                     source=source,
                                     detail_type=detail_type,
                                     schema_content=schema_content)

    @staticmethod
    def _is_local_bus(target_event_bus: IEventBus):
        return not re.compile('-(dev|int|tp|prod|prod-p)$').match(target_event_bus.event_bus_name)
