from enum import Enum, auto
from typing import Mapping, Optional, cast

import constructs
from aws_cdk import Duration
from aws_cdk.aws_dynamodb import ITable, Table
from aws_cdk.aws_stepfunctions import Choice, Condition, DefinitionBody, Fail, IChainable, JsonPath, Pass, StateMachine, \
    Succeed, TaskInput, Wait, WaitTime
from aws_cdk.aws_stepfunctions_tasks import DynamoAttributeValue, DynamoGetItem, DynamoPutItem, DynamoUpdateItem, \
    LambdaInvoke
from bb_fnds.cdk_constructs import pipeline_forge

from cdk.dynamodb import Dynamodb
from cdk.lambdas import Lambdas
from cdk.stack_inputs import StackInputs


class StepFunctions(constructs.Construct):
    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: StackInputs, lambdas: Lambdas, dynamodb: Dynamodb):
        super().__init__(stack, 'StepFunctions')
        self.stack = stack

        self._define_create_step(lambdas, dynamodb, stack_inputs)
        self._define_update_step(lambdas, dynamodb, stack_inputs)
        self._define_delete_step(lambdas, dynamodb, stack_inputs)

    def _define_create_step(self, lambdas, dynamodb, stack_inputs):
        step_function = CreateTenantResourceStepFunction(self, 'CreateResourcesStep', self.stack, stack_inputs, lambdas,
                                                         dynamodb.tenant_resources_table)

        # allow the get_queue lambda to start our step function
        step_function.state_machine.grant_start_execution(lambdas.get_queue.function.role)
        lambdas.get_queue.function.add_environment(key="TENANT_PROVISIONER_ARN",
                                                   value=step_function.state_machine.state_machine_arn)

    def _define_update_step(self, lambdas, dynamodb, stack_inputs):
        UpdateTenantResourceStepFunction(self, 'UpdateResourcesStep', self.stack, stack_inputs, lambdas,
                                         dynamodb.tenant_resources_table)

    def _define_delete_step(self, lambdas, dynamodb, stack_inputs):
        delete_tenant_resources_step = DeleteTenantResourceStepFunction(self, 'DeleteResourcesStep', self.stack,
                                                                        stack_inputs, lambdas,
                                                                        dynamodb.tenant_resources_table)

        for monitored_lambda in [lambdas.delete_queues, lambdas.tenant_event_handler]:
            monitored_lambda.function.add_environment(
                key="TENANT_DELETE_ARN", value=delete_tenant_resources_step.state_machine.state_machine_arn)
            delete_tenant_resources_step.state_machine.grant_start_execution(monitored_lambda.function.role)


class TenantResourceStepFunctionType(Enum):
    CREATE = auto()
    UPDATE = auto()
    DELETE = auto()


class TenantResourceStepFunction(constructs.Construct):
    state_machine: StateMachine

    def __init__(self, scope: constructs.Construct, _id: str, stack: pipeline_forge.Stack, stack_inputs: StackInputs,
                 lambdas: Lambdas, dynamodb_table: Table, *, parameters: list[str]):
        super().__init__(scope, _id)
        self.stack = stack
        self.stack_inputs = stack_inputs
        self.lambdas = lambdas
        self.dynamodb_table = dynamodb_table
        self.parameters = parameters

        # Core termination steps
        self.success_step: IChainable = cast(IChainable, Succeed(self, 'Success'))
        self.failure_step: IChainable = cast(IChainable, Fail(self, 'Failure'))

    def parse_input(self):
        # Check for the default parameters
        parameters = {
            f"{param}.$": f"$.{param}"
            for param in self.parameters
        }

        # Pre-format this value so we can use it when interacting with DynamoDB later
        parameters["tenantPk.$"] = "States.Format('TENANT_ID#{}', $.tenantId)"

        return Pass(self, 'ParseInput', parameters=parameters)

    def get_tenant_metadata(self):
        return DynamoGetItem(self,
                             'GetTenantMetadata',
                             table=cast(ITable, self.dynamodb_table),
                             key=self._dict_to_dynamo_mapping({
                                 "pk": JsonPath.string_at("$.tenantPk"),
                                 "sk": "METADATA"
                             }),
                             result_path="$.GetTenantMetadata")

    def create_audit_row(self, audit_sort_key: str, dynamic_params: Optional[dict[str, str]] = None):
        if not dynamic_params:
            dynamic_params = {}

        status = "Started"
        put_item = DynamoPutItem(
            self,
            f'{status}BuildAudit',
            table=cast(ITable, self.dynamodb_table),
            item=self._dict_to_dynamo_mapping({
                "pk": JsonPath.string_at("$.tenantPk"),
                "sk": audit_sort_key,
                "Status": status,
                "CreatedAt": JsonPath.string_at("$$.State.EnteredTime"),
                "UpdatedAt": JsonPath.string_at("$$.State.EnteredTime"),
                "Execution": JsonPath.string_at("$$.Execution.Id"),
                "Version": self.lambdas.tenant_resources_version,
                **dynamic_params
            }),
            result_path="$.PutItemOutput",
            # ensure parallel step function executions can't step on each other
            condition_expression="(attribute_not_exists(pk) AND attribute_not_exists(sk)) OR #status <> :status",
            expression_attribute_names={
                "#status": "Status"
            },
            expression_attribute_values=self._dict_to_dynamo_mapping({
                ":status": status
            }))

        # If our condition_expression prevented the put, it's likely another execution is running for the same
        # tenant. Mark this execution as succeeded without touching the audit row, and trust that the other execution
        # will trigger an alarm if something goes wrong.
        put_item.add_catch(errors=["DynamoDB.ConditionalCheckFailedException"], handler=self.success_step)

        return put_item

    def update_audit_row(self, audit_sort_key: str, status: str):
        return DynamoUpdateItem(
            self,
            f'{status}BuildAudit',
            table=cast(ITable, self.dynamodb_table),
            key=self._dict_to_dynamo_mapping({
                "pk": JsonPath.string_at("$.tenantPk"),
                "sk": audit_sort_key
            }),
            update_expression="SET #status = :status, UpdatedAt = :updatedAt",
            expression_attribute_names={
                "#status": "Status"
            },
            expression_attribute_values=self._dict_to_dynamo_mapping({
                ":status": status,
                ":updatedAt": JsonPath.string_at("$$.State.EnteredTime")
            }),
            result_path="$.UpdateItemOutput",
        )

    @staticmethod
    def _dict_to_dynamo_mapping(item: dict[str, str]) -> Mapping[str, DynamoAttributeValue]:
        return {
            k: DynamoAttributeValue.from_string(v)
            for k, v in item.items()
        }

    def end_state_audit_handlers(self, audit_sort_key):
        success_build_audit = self.update_audit_row(audit_sort_key, "Success").next(self.success_step)
        failure_build_audit = self.update_audit_row(audit_sort_key, "Failure").next(self.failure_step)
        return success_build_audit, failure_build_audit

    def generate_state_machine(self, _id: str, definition: IChainable, function_type: TenantResourceStepFunctionType):
        self.state_machine = StateMachine(self,
                                          "StateMachine",
                                          definition_body=DefinitionBody.from_chainable(definition),
                                          state_machine_name=f'{self.stack.stack_name}-{function_type.name.lower()}',
                                          tracing_enabled=True)

        self._grant_permissions_and_set_alarms(_id)

    def _grant_permissions_and_set_alarms(self, _id: str):
        self.dynamodb_table.grant_read_write_data(self.state_machine.role)

    @staticmethod
    def _add_lambda_retry(lambda_invoke: LambdaInvoke, failure_build_audit: IChainable):
        lambda_invoke.add_catch(handler=failure_build_audit, result_path="$.Failure")
        lambda_invoke.add_retry(interval=Duration.seconds(5), max_attempts=5)


class CreateTenantResourceStepFunction(TenantResourceStepFunction):
    def __init__(self, scope: constructs.Construct, _id: str, stack: pipeline_forge.Stack, stack_inputs: StackInputs,
                 lambdas: Lambdas, dynamodb_table: Table):
        super().__init__(scope,
                         _id,
                         stack,
                         stack_inputs,
                         lambdas,
                         dynamodb_table,
                         parameters=["tenantId", "currentCount", "retryCount", "clientId"])

        function_type = TenantResourceStepFunctionType.CREATE
        audit_sort_key = f"AUDIT#{function_type.name}"

        parse_input = self.parse_input()

        started_build_audit = self.create_audit_row(audit_sort_key, {
            "RetryCount": JsonPath.string_at("$.currentCount"),
            "ClientId": JsonPath.string_at("$.clientId"),
        })
        success_build_audit, failure_build_audit = self.end_state_audit_handlers(audit_sort_key)

        create_tenant_stack = LambdaInvoke(self,
                                           'CreateTenantStack',
                                           lambda_function=lambdas.tenant_resources_deploy_stack.alias,
                                           payload=TaskInput.from_object({
                                               'tenantId': JsonPath.string_at('$.tenantId'),
                                               'clientId': JsonPath.string_at('$.clientId'),
                                           }),
                                           result_path='$.CreateTenantStack')
        self._add_lambda_retry(create_tenant_stack, failure_build_audit)

        wait_for_create: IChainable = cast(IChainable, Wait(self, 'Sleep',
                                                            time=WaitTime.duration(Duration.seconds(15))))

        get_stack_status = LambdaInvoke(self,
                                        'GetStackStatus',
                                        lambda_function=lambdas.tenant_resources_get_stack_status.alias,
                                        payload=TaskInput.from_object({
                                            'stackName': JsonPath.string_at('$.CreateTenantStack.Payload.stackId'),
                                        }),
                                        result_path='$.GetStackStatus')
        self._add_lambda_retry(get_stack_status, failure_build_audit)

        validate_status = Choice(self, 'ValidateStatus')
        validate_status.when(Condition.boolean_equals('$.GetStackStatus.Payload.isFailure', True), failure_build_audit)
        validate_status.when(Condition.string_equals('$.GetStackStatus.Payload.status', 'DELETE_COMPLETE'),
                             failure_build_audit)
        validate_status.when(Condition.boolean_equals('$.GetStackStatus.Payload.isComplete', True), success_build_audit)
        validate_status.otherwise(wait_for_create)

        # noinspection PyTypeChecker
        definition: IChainable = parse_input\
            .next(started_build_audit)\
            .next(create_tenant_stack)\
            .next(wait_for_create)\
            .next(get_stack_status)\
            .next(validate_status)

        self.generate_state_machine(_id, definition, function_type)


class UpdateTenantResourceStepFunction(TenantResourceStepFunction):
    def __init__(self, scope: constructs.Construct, _id: str, stack: pipeline_forge.Stack, stack_inputs: StackInputs,
                 lambdas: Lambdas, dynamodb_table: Table):
        super().__init__(scope, _id, stack, stack_inputs, lambdas, dynamodb_table, parameters=["tenantId"])

        function_type = TenantResourceStepFunctionType.UPDATE
        audit_sort_key = f"AUDIT#{function_type.name}#{lambdas.tenant_resources_version}"

        parse_input = self.parse_input()
        get_tenant_metadata = self.get_tenant_metadata()

        started_build_audit = self.create_audit_row(audit_sort_key)
        success_build_audit, failure_build_audit = self.end_state_audit_handlers(audit_sort_key)

        update_tenant_stack = LambdaInvoke(self,
                                           'UpdateTenantStack',
                                           lambda_function=lambdas.tenant_resources_deploy_stack.alias,
                                           payload=TaskInput.from_object({
                                               'tenantId': JsonPath.string_at('$.tenantId'),
                                               'clientId': JsonPath.string_at("$.GetTenantMetadata.Item.ClientId.S"),
                                               'isUpdate': True,
                                           }),
                                           result_path='$.UpdateTenantStack')
        self._add_lambda_retry(update_tenant_stack, failure_build_audit)

        wait_for_update: IChainable = cast(IChainable, Wait(self, 'Sleep',
                                                            time=WaitTime.duration(Duration.seconds(15))))

        get_stack_status = LambdaInvoke(self,
                                        'GetStackStatus',
                                        lambda_function=lambdas.tenant_resources_get_stack_status.alias,
                                        payload=TaskInput.from_object({
                                            'stackName': JsonPath.string_at('$.UpdateTenantStack.Payload.stackName'),
                                        }),
                                        result_path='$.GetStackStatus')
        self._add_lambda_retry(get_stack_status, failure_build_audit)

        validate_status = Choice(self, 'ValidateStatus')
        validate_status.when(Condition.boolean_equals('$.GetStackStatus.Payload.isFailure', True), failure_build_audit)
        validate_status.when(Condition.boolean_equals('$.GetStackStatus.Payload.isComplete', True), success_build_audit)
        validate_status.otherwise(wait_for_update)

        # noinspection PyTypeChecker
        run_upgrade: IChainable = started_build_audit\
            .next(update_tenant_stack)\
            .next(wait_for_update)\
            .next(get_stack_status)\
            .next(validate_status)

        validate_version = Choice(self, 'ValidateVersion')
        validate_version.when(
            Condition.string_equals('$.GetTenantMetadata.Item.Version.S', lambdas.tenant_resources_version),
            success_build_audit)
        validate_version.otherwise(run_upgrade)

        # noinspection PyTypeChecker
        definition: IChainable = parse_input\
            .next(get_tenant_metadata)\
            .next(validate_version)

        self.generate_state_machine(_id, definition, function_type)


class DeleteTenantResourceStepFunction(TenantResourceStepFunction):
    def __init__(self, scope: constructs.Construct, _id: str, stack: pipeline_forge.Stack, stack_inputs: StackInputs,
                 lambdas: Lambdas, dynamodb_table: Table):
        super().__init__(scope, _id, stack, stack_inputs, lambdas, dynamodb_table, parameters=["tenantId"])

        function_type = TenantResourceStepFunctionType.DELETE
        audit_sort_key = f"AUDIT#{function_type.name}"

        parse_input = self.parse_input()
        get_tenant_metadata = self.get_tenant_metadata()

        started_build_audit = self.create_audit_row(audit_sort_key)
        success_build_audit, failure_build_audit = self.end_state_audit_handlers(audit_sort_key)

        delete_tenant_stack = LambdaInvoke(self,
                                           'DeleteTenantStack',
                                           lambda_function=lambdas.tenant_resources_destroy_stack.alias,
                                           payload=TaskInput.from_object({
                                               'tenantId': JsonPath.string_at('$.tenantId'),
                                           }),
                                           result_path='$.DeleteTenantStack')
        self._add_lambda_retry(delete_tenant_stack, failure_build_audit)

        wait_for_delete: IChainable = cast(IChainable, Wait(self, 'Sleep',
                                                            time=WaitTime.duration(Duration.seconds(30))))

        get_stack_status = LambdaInvoke(self,
                                        'GetStackStatus',
                                        lambda_function=lambdas.tenant_resources_get_stack_status.alias,
                                        payload=TaskInput.from_object({
                                            'stackName': JsonPath.string_at('$.DeleteTenantStack.Payload.stackName'),
                                        }),
                                        result_path='$.GetStackStatus')
        self._add_lambda_retry(get_stack_status, failure_build_audit)

        validate_status = Choice(self, 'ValidateStatus')
        validate_status.when(Condition.boolean_equals('$.GetStackStatus.Payload.isFailure', True), failure_build_audit)
        validate_status.when(Condition.string_equals('$.GetStackStatus.Payload.status', 'DELETE_COMPLETE'),
                             success_build_audit)
        validate_status.otherwise(wait_for_delete)

        # noinspection PyTypeChecker
        definition: IChainable = parse_input\
            .next(get_tenant_metadata)\
            .next(started_build_audit)\
            .next(delete_tenant_stack)\
            .next(wait_for_delete)\
            .next(get_stack_status)\
            .next(validate_status)

        self.generate_state_machine(_id, definition, function_type)
