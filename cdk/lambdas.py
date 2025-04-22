import json
from typing import Optional, cast

import aws_cdk.aws_iam as iam
import aws_cdk.aws_logs as logs
import constructs
from aws_cdk import Duration
from aws_cdk.aws_codedeploy import LambdaDeploymentConfig, LambdaDeploymentGroup
from aws_cdk.aws_events import EventPattern, Rule
from aws_cdk.aws_events_targets import LambdaFunction, SqsQueue
from aws_cdk.aws_lambda import Alias, Architecture, Function, ILayerVersion, Runtime, Tracing
from aws_cdk.aws_lambda_event_sources import SqsEventSource
from aws_cdk.aws_sqs import DeadLetterQueue, QueueEncryption
from bb_ent_data_services_shared.cdk.util import override_logical_id
from bb_fnds.cdk_constructs import bundler, event_hub, lambdas as cc_lambdas, pipeline_forge, service_discovery

from cdk.common_dlqs import CommonDeadLetterQueues
from cdk.core.alarms import Alarms
from cdk.core.cloudwatch import CloudWatch
from cdk.core.lambdas import CoreLambdas
from cdk.core.stack_inputs import LambdaEventFunctionOverrides, LambdaFunctionOverrides
from cdk.dynamodb import Dynamodb
from cdk.eventbridge import Eventbridge
from cdk.stack_inputs import StackInputs


class Lambdas(constructs.Construct):
    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: StackInputs, dynamodb: Dynamodb,
                 eventbridge: Eventbridge, cloudwatch: CloudWatch, alarms: Alarms, common_dlqs: CommonDeadLetterQueues):
        super().__init__(stack, 'Lambdas')

        self.stack = stack
        self.stack_inputs = stack_inputs
        self.dynamodb = dynamodb
        self.eventbridge = eventbridge
        self.cloudwatch = cloudwatch
        self.alarms = alarms
        self.common_dlqs = common_dlqs
        self.core_lambdas = CoreLambdas(alarms)

        self.runtime: Runtime = cast(Runtime, Runtime.PYTHON_3_11)
        self.library_layer = cc_lambdas.PythonLayer(self,
                                                    'LibraryLayer',
                                                    layer_version_name=f'{stack.stack_name}-libraries',
                                                    compatible_runtimes=[self.runtime],
                                                    entry='layers/libraries')

        self.common_layer = cc_lambdas.PythonLayer(self,
                                                   'CommonLayer',
                                                   layer_version_name=f"{stack.stack_name}-common",
                                                   compatible_runtimes=[self.runtime],
                                                   entry='layers/common',
                                                   bundling_props=bundler.PythonBundlingProps(path='layers/common',
                                                                                              include_basename=True))

        self.common_env = {
            'EVENT_BUS': eventbridge.enterprise_objects_bus.event_bus_name,
            'TABLE_NAME': dynamodb.tenant_resources_table.table_name,
            'STACK_NAME': stack.stack_name,
            'LOG_LEVEL': stack_inputs.lambdas.log_level,
            'POWERTOOLS_SERVICE_NAME': stack.stack_name,
        }

        self.sqs_wildcard_arn: str = f'arn:{stack.partition}:sqs:{stack.region}:{stack.account}:{stack.stack_name}-*'

        # List of REST API lambdas
        self.rest_apis: list[MonitoredLambda] = []

        self._create_sqs_event_handler()
        self._create_rest_get_queue()
        self._create_rest_get_queues()
        self._create_rest_delete_queues()
        self._create_eventbridge_event_handler()
        self._create_tenant_event_handler()
        self._create_tenant_resources_manage_metadata()
        self._create_tenant_resources_deploy_stack()
        self._create_tenant_resources_get_stack_status()
        self._create_tenant_resources_destroy_stack()

        # Scaling/Performance alarms
        cloudwatch.lambda_rest_concurrency_alarm()

    def _create_sqs_event_handler(self):
        overrides = self.stack_inputs.lambdas.sqs_to_eventbridge
        overrides.alarms.set_defaults(
            throttling_enabled=False,  # Has alarm on SQS message age
        )
        overrides.set_sqs_alarm_defaults(message_age_threshold=Duration.hours(1))

        # Shared queue that all Learns send their Foundations events to
        self.outbound_queue = self.core_lambdas.sqs_queue(
            self,
            'outbound',
            overrides.queue_alarm,
            visibility_timeout=Duration.minutes(1),
            dead_letter_queue=DeadLetterQueue(max_receive_count=10, queue=self.common_dlqs.outbound_dlq))

        self.sqs_to_eventbridge = MonitoredLambda(self,
                                                  'SqsToEventbridge',
                                                  overrides=overrides,
                                                  entry='functions/event_source/sqs_to_eventbridge',
                                                  handler='sqs_to_eventbridge.handler',
                                                  retry_attempts=2,
                                                  reserved_concurrent_executions=(overrides.reserved_concurrency or 2),
                                                  memory_size=256)

        self.eventbridge.enterprise_objects_bus.grant_put_events_to(self.sqs_to_eventbridge.function)
        self.sqs_to_eventbridge.function.role.add_to_policy(
            iam.PolicyStatement(
                resources=[self.sqs_wildcard_arn],
                actions=["sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ReceiveMessage"]))

        # Subscribe to SQS events
        self.sqs_to_eventbridge.alias.add_event_source(SqsEventSource(queue=self.outbound_queue, batch_size=10))

    def _create_rest_get_queue(self):
        overrides = self.stack_inputs.lambdas.get_queue
        overrides.alarms.set_defaults(
            availability_enabled=False,  # Has alarm on API Gateway metrics
        )

        self.get_queue = MonitoredLambda(
            self,
            'GetQueueFunction',
            overrides=overrides,
            rest_api=True,
            entry='functions/rest_api/get_queue',
            handler='get_queue.handler',
            reserved_concurrent_executions=overrides.reserved_concurrency,
            environment={
                **self.common_env,
                'OUTBOUND_QUEUE_ARN': self.outbound_queue.queue_arn,
                'OUTBOUND_QUEUE_URL': self.outbound_queue.queue_url,
            },
        )

        self.dynamodb.tenant_resources_table.grant_read_data(self.get_queue.function)

        sqs_role = iam.Role(self,
                            'SqsAssumeRole',
                            assumed_by=iam.ArnPrincipal(arn=self.get_queue.function.role.role_arn))
        sqs_role.add_to_policy(
            iam.PolicyStatement(
                resources=[self.sqs_wildcard_arn],
                actions=["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]))
        self.get_queue.function.role.add_to_policy(
            iam.PolicyStatement(resources=[sqs_role.role_arn], actions=['sts:assumerole']))
        self.get_queue.function.add_environment("ASSUMABLE_SQS_ROLE", sqs_role.role_arn)

        #
        # Tenant API service discovery
        #

        if self.stack.is_il4:
            # Allow developers to use the IL4 Dev stack
            service_discovery.Subscription.map_local_to_dev()
        else:
            # Allow developers to use the Int stack (registrar-blue-next)
            service_discovery.Subscription.map_local_to_int()

        tenant_service = service_discovery.Subscription(self,
                                                        'TenantServiceSubscription',
                                                        name='tenancy-tenant',
                                                        type=service_discovery.ServiceType.API)
        self.get_queue.function.add_environment('TENANT_DISCOVERY_HOST', tenant_service.domain_name)

        # Allow Lambda to call Tenant API
        self.get_queue.function.role.add_to_policy(
            iam.PolicyStatement(
                actions=['execute-api:Invoke'],
                resources=['*'],
            ))

        if not overrides.only_saas_tenants:
            self.get_queue.function.add_environment('ALLOW_NON_SAAS_TENANTS', '1')
        if overrides.skip_tenant_api_errors or not overrides.only_saas_tenants:
            self.get_queue.function.add_environment('SKIP_TENANT_API_ERRORS', '1')

        # Reset mapping so we only handle this one event type from Int
        service_discovery.Subscription.map_local_to_local()

    def _create_rest_get_queues(self):
        overrides = self.stack_inputs.lambdas.get_queues
        overrides.alarms.set_defaults(
            availability_enabled=False,  # Has alarm on API Gateway metrics
        )

        self.get_queues = MonitoredLambda(
            self,
            'GetQueuesFunction',
            overrides=overrides,
            rest_api=True,
            entry='functions/rest_api/get_queues',
            handler='get_queues.handler',
        )
        self.dynamodb.tenant_resources_table.grant_read_data(self.get_queues.function)

    def _create_rest_delete_queues(self):
        overrides = self.stack_inputs.lambdas.delete_queues
        overrides.alarms.set_defaults(
            availability_enabled=False,  # Has alarm on API Gateway metrics
        )

        self.delete_queues = MonitoredLambda(
            self,
            'DeleteQueuesFunction',
            overrides=overrides,
            rest_api=True,
            entry='functions/rest_api/delete_queues',
            handler='delete_queues.handler',
        )
        self.dynamodb.tenant_resources_table.grant_read_data(self.delete_queues.function)

    def _create_eventbridge_event_handler(self):
        overrides = self.stack_inputs.lambdas.eventbridge_to_sqs
        overrides.alarms.set_defaults()
        overrides.set_sqs_alarm_defaults()

        eventbridge_dlq = self.core_lambdas.sqs_queue(
            self,
            "EventbridgeToSqsDlq",
            overrides.dlq_alarm,
            queue_name=None,  # Queue was originally created without a name
        )

        self.eventbridge_to_sqs = MonitoredLambda(self,
                                                  'EventBridgeToSqsFunction',
                                                  overrides=overrides,
                                                  entry='functions/event_source/eventbridge_to_sqs',
                                                  dead_letter_queue=eventbridge_dlq,
                                                  handler='eventbridge_to_sqs.handler',
                                                  reserved_concurrent_executions=(overrides.reserved_concurrency or 2),
                                                  memory_size=160)
        self.eventbridge_to_sqs.function.role.add_to_policy(
            iam.PolicyStatement(resources=[self.sqs_wildcard_arn], actions=["sqs:*"]))
        self.dynamodb.tenant_resources_table.grant_read_data(self.eventbridge_to_sqs.function)

        # Such events are ignored if there are no queues for the specified tenant
        self.eventbridge_to_sqs.function.add_environment('EVENTS_IGNORED_WHEN_QUEUE_MISSING',
                                                         json.dumps(self.eventbridge.events_ignore_missing_tenants))

        ping_rule = Rule(self.stack,
                         'PingEventRule',
                         event_bus=self.eventbridge.enterprise_objects_bus,
                         event_pattern=EventPattern(detail_type=["FoundationsConnectorPing"]))
        ping_rule.add_target(LambdaFunction(handler=self.eventbridge_to_sqs.alias))

        # Route subscribed events from the Foundations service to this Lambda
        for subscription in self.eventbridge.learn_rule_subscriptions:
            subscription.add_target(LambdaFunction(handler=self.eventbridge_to_sqs.alias))

        # Disabled event source mappings, which SRE can temporarily enable if we want to replay events from the DLQs and
        # give Learn a second chance to handle them.
        self.eventbridge_to_sqs.alias.add_event_source(
            SqsEventSource(queue=self.common_dlqs.inbound_dlq, batch_size=10, enabled=False))
        self.eventbridge_to_sqs.alias.add_event_source(
            SqsEventSource(queue=eventbridge_dlq, batch_size=10, enabled=False))

    def _create_tenant_event_handler(self):
        overrides = self.stack_inputs.lambdas.tenant_event_handler
        overrides.alarms.set_defaults(
            duration_enabled=False,  # Deletes are expected to be slow
        )
        if not overrides.timeout_seconds:
            overrides.timeout_seconds = Duration.minutes(15).to_seconds()
        if overrides.queue_visibility_timeout_seconds is None:
            # AWS recommends timeout*6 because the Lambda invocation itself may be retried thrice after reading once
            # from the SQS, but in practice that is rare and the event-handler Lambdas have to be idempotent anyway.
            overrides.queue_visibility_timeout_seconds = overrides.timeout_seconds * 2
        overrides.set_sqs_alarm_defaults(message_age_threshold=Duration.days(1))

        # Dead letter queue
        event_dlq = self.core_lambdas.sqs_queue(
            self,
            "TenantEventHandlerDlq",
            overrides.dlq_alarm,
            queue_name=None,  # Queue was originally created without a name
        )

        # SQS queue to buffer events from EventBridge
        event_queue_name = 'TenantEventHandlerQueue'
        visibility_timeout = Duration.seconds(overrides.queue_visibility_timeout_seconds or 1080)
        event_queue = self.core_lambdas.sqs_queue(self,
                                                  event_queue_name,
                                                  overrides.queue_alarm,
                                                  visibility_timeout=visibility_timeout,
                                                  encryption=QueueEncryption.KMS,
                                                  encryption_master_key=self.eventbridge.eventbridge_sqs_kms_key,
                                                  dead_letter_queue=DeadLetterQueue(max_receive_count=50,
                                                                                    queue=event_dlq))

        # Lambda event listener
        self.tenant_event_handler = MonitoredLambda(
            self,
            'TenantEventHandlerFunction',
            overrides=overrides,
            timeout=Duration.seconds(overrides.timeout_seconds),
            entry='functions/event_source/tenant_event_handler',
            dead_letter_queue=event_dlq,
            handler='tenant_event_handler.handler',
            reserved_concurrent_executions=(overrides.reserved_concurrency or 2),
        )

        # Subscribe to SQS events
        self.tenant_event_handler.alias.add_event_source(
            SqsEventSource(queue=event_queue, batch_size=10, report_batch_item_failures=True))

        # Lambda permissions
        self.dynamodb.tenant_resources_table.grant_read_data(self.tenant_event_handler.function)

        if self.stack.is_il4:
            # Allow developers to receive events from the IL4 Dev stack
            event_hub.Subscription.map_local_to_dev()
        else:
            # Allow developers to receive events from the Int stack (registrar-blue-next)
            event_hub.Subscription.map_local_to_int()

        # Subscribe the SQS queue to EventBridge
        event_source = event_hub.Subscription(self.stack,
                                              "TenantDeletedSubscription",
                                              source="bb.tenant",
                                              detail_type="Tenant Deleted",
                                              target_event_bus=self.eventbridge.private_event_bus)
        event_source.add_target(SqsQueue(queue=event_queue))

        # Reset mapping so we only handle this one event type from Int
        event_hub.Subscription.map_local_to_local()

    def _create_tenant_resources_manage_metadata(self):
        overrides = self.stack_inputs.lambdas.tenant_resources_manage_metadata
        overrides.alarms.set_defaults()

        self.tenant_resources_manage_metadata = MonitoredLambda(
            self,
            'ManageTenantMetadata',
            overrides=overrides,
            entry='functions/tenant_resources/manage_metadata',
            handler='manage_metadata.handler',
            reserved_concurrent_executions=(overrides.reserved_concurrency or 2))
        self.dynamodb.tenant_resources_table.grant_read_write_data(self.tenant_resources_manage_metadata.function.role)

    def _create_tenant_resources_deploy_stack(self):
        overrides = self.stack_inputs.lambdas.tenant_resources_deploy_stack
        overrides.alarms.set_defaults()
        overrides.deployment_group_error_rate_alarm_config.set_defaults(evaluation_periods=3)

        with open('functions/tenant_resources/deploy_stack/version.txt', 'r', encoding='ascii') as file:
            self.tenant_resources_version = file.readline().rstrip('\n')

        stack_tags = json.dumps(self.stack_inputs.tags)

        self.tenant_resources_deploy_stack = MonitoredLambda(
            self,
            'DeployTenantStack',
            overrides=overrides,
            entry='functions/tenant_resources/deploy_stack',
            handler='deploy_stack.handler',
            environment={
                **self.common_env,
                'MANAGE_METADATA_ARN': self.tenant_resources_manage_metadata.alias.function_arn,
                'PAGER_DUTY_ALARM_WARNING_TOPIC': self.cloudwatch.warning_topic.topic_arn
                if self.cloudwatch.warning_topic else "",
                'INBOUND_DLQ_ARN': self.common_dlqs.inbound_dlq.queue_arn,
                'STACK_VERSION': self.tenant_resources_version,
                'STACK_TAGS': stack_tags,
            },
            reserved_concurrent_executions=(overrides.reserved_concurrency or 2),
            timeout=Duration.seconds(30))

        # manage tenant cloudformation stacks
        self._grant_cloudformation_permission(self.tenant_resources_deploy_stack.function.role)

    def _create_tenant_resources_get_stack_status(self):
        overrides = self.stack_inputs.lambdas.tenant_resources_get_stack_status
        overrides.alarms.set_defaults()
        overrides.deployment_group_error_rate_alarm_config.set_defaults(evaluation_periods=3)

        self.tenant_resources_get_stack_status = MonitoredLambda(
            self,
            'TenantStackStatus',
            overrides=overrides,
            entry='functions/tenant_resources/get_stack_status',
            handler='get_stack_status.handler',
            reserved_concurrent_executions=(overrides.reserved_concurrency or 2))

        # view cloudformation
        role = self.tenant_resources_get_stack_status.function.role
        role.add_to_policy(
            iam.PolicyStatement(actions=['cloudformation:DescribeStacks'],
                                resources=[
                                    f'arn:{self.stack.partition}:cloudformation:{self.stack.region}'
                                    f':{self.stack.account}:stack/{self.stack.stack_name}*'
                                ]))

    def _create_tenant_resources_destroy_stack(self):
        overrides = self.stack_inputs.lambdas.tenant_resources_destroy_stack
        overrides.alarms.set_defaults()
        overrides.deployment_group_error_rate_alarm_config.set_defaults(evaluation_periods=3)

        self.tenant_resources_destroy_stack = MonitoredLambda(
            self,
            'DestroyTenantStack',
            overrides=overrides,
            entry='functions/tenant_resources/destroy_stack',
            handler='destroy_stack.handler',
            reserved_concurrent_executions=(overrides.reserved_concurrency or 2),
            timeout=Duration.seconds(30))

        # manage tenant cloudformation stacks
        self._grant_cloudformation_permission(self.tenant_resources_destroy_stack.function.role)

    def _grant_cloudformation_permission(self, role):
        # manage the tenant stack
        role.add_to_policy(
            iam.PolicyStatement(actions=['cloudformation:*'],
                                resources=[
                                    f'arn:{self.stack.partition}:cloudformation:{self.stack.region}'
                                    f':{self.stack.account}:stack/{self.stack.stack_name}*'
                                ]))

        # manage eventsource mapping
        role.add_to_policy(
            iam.PolicyStatement(resources=["*"],
                                actions=[
                                    'lambda:ListEventSourceMappings',
                                    'lambda:GetEventSourceMapping',
                                ]))
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    'lambda:CreateEventSourceMapping',
                    'lambda:UpdateEventSourceMapping',
                    'lambda:DeleteEventSourceMapping',
                ],
                resources=['*'],
                conditions={
                    "StringEquals": {
                        "lambda:functionArn": [
                            self.sqs_to_eventbridge.function.function_arn, self.sqs_to_eventbridge.alias.function_arn
                        ]
                    }
                },
            ))

        # manage sqs
        role.add_to_policy(
            iam.PolicyStatement(actions=['sqs:*'],
                                resources=[
                                    f'arn:{self.stack.partition}:sqs:{self.stack.region}'
                                    f':{self.stack.account}:{self.stack.stack_name}-*'
                                ]))

        # manage dlq alarms
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:DeleteAlarms", "cloudwatch:EnableAlarmActions", "cloudwatch:GetMetricData",
                    "cloudwatch:PutMetricAlarm"
                ],
                resources=['*'],
            ))

        # manage dynamodb metadata row
        self.tenant_resources_manage_metadata.alias.grant_invoke(role)


class MonitoredLambda(constructs.Construct):
    function: Function
    alias: Alias
    deployment_group: Optional[LambdaDeploymentGroup]

    def __init__(self,
                 lambdas: Lambdas,
                 _id: str,
                 *,
                 overrides: LambdaFunctionOverrides,
                 rest_api: bool = False,
                 entry: str,
                 reserved_concurrent_executions: Optional[int] = None,
                 **kwargs):
        super().__init__(lambdas, _id)

        if 'environment' not in kwargs:
            kwargs['environment'] = lambdas.common_env
        if 'timeout' not in kwargs:
            kwargs['timeout'] = Duration.seconds(10)
        if 'architecture' not in kwargs:
            kwargs['architecture'] = Architecture.ARM_64

        self.function = cc_lambdas.PythonFunction(
            self,
            'Function',
            entry=entry,
            runtime=lambdas.runtime,
            layers=[cast(ILayerVersion, lambdas.library_layer),
                    cast(ILayerVersion, lambdas.common_layer)],
            reserved_concurrent_executions=reserved_concurrent_executions,
            log_retention=logs.RetentionDays.THREE_MONTHS,
            tracing=Tracing.ACTIVE,
            **kwargs)

        if rest_api:
            lambdas.cloudwatch.add_rest_lambda_function(self.function)

        self.alias = self.function.add_alias('live')

        # Use a static logical ID so we can reference it from our OpenAPI spec
        alias_id = f'{_id}Alias'
        if rest_api:
            lambdas.rest_apis.append(self)
        else:
            # CDK v2 deprecated self.function.current_version.add_alias, but did not give us a path to migrate existing
            # aliases without renaming them. We cannot rename our current aliases without updating all of the tenant,
            # stacks, as each stack has an event source mapping linking their SQS queue to the SqsToEventbridge Lambda.
            # This ensures we continue to use the same logical ID as before.
            legacy_ids = {
                'DeployTenantStack': 'LambdasDeployTenantStackFunctionCurrentVersionAliasliveF32E917B',
                'DestroyTenantStack': 'LambdasDestroyTenantStackFunctionCurrentVersionAliaslive565F98D0',
                'EventBridgeToSqsFunction': 'LambdasEventBridgeToSqsFunctionCurrentVersionAliaslive7A2E54F6',
                'ManageTenantMetadata': 'LambdasManageTenantMetadataFunctionCurrentVersionAliaslive75758200',
                'SqsToEventbridge': 'LambdasSqsToEventbridgeFunctionCurrentVersionAliasliveCAEBA3F8',
                'TenantEventHandlerFunction': 'LambdasTenantEventHandlerFunctionCurrentVersionAliaslive7F1C46AA',
                'TenantStackStatus': 'LambdasTenantStackStatusFunctionCurrentVersionAliasliveB25E9D93',
            }
            if logical_id := legacy_ids.get(_id):
                alias_id = logical_id
        override_logical_id(self.alias, alias_id)

        if lambdas.stack_inputs.lambdas.blue_green_deployment:
            # Support blue-green deployments in production
            if lambdas.stack.stage == 'prod':
                deployment_config = LambdaDeploymentConfig.CANARY_10_PERCENT_10_MINUTES
            else:
                deployment_config = LambdaDeploymentConfig.ALL_AT_ONCE
            self.deployment_group = LambdaDeploymentGroup(self,
                                                          "BlueGreenDeploy",
                                                          alias=self.alias,
                                                          deployment_config=cast(LambdaDeploymentConfig,
                                                                                 deployment_config))

            overrides.deployment_group_error_rate_alarm_config.set_defaults(threshold=5,
                                                                            evaluation_periods=1,
                                                                            minimum_invocations=1)
            self.deployment_group.add_alarm(
                lambdas.cloudwatch.lambda_error_rate_alarm(
                    self.alias, name=_id, alarm_config=overrides.deployment_group_error_rate_alarm_config))
        else:
            # Skip blue-green deployment in dev
            self.deployment_group = None

        # Alarm if events attempted to be sent to dead letter queues but fail
        if kwargs.get('dead_letter_queue'):
            overrides = cast(LambdaEventFunctionOverrides, overrides)
            lambdas.cloudwatch.lambda_add_dlq_alarms(_id,
                                                     self.function,
                                                     dlq_send_error_alarm_config=overrides.dlq_send_error_alarm_config)

        lambdas.alarms.monitor_lambda(self.function, overrides.alarms)
