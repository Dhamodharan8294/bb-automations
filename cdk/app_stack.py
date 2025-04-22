from bb_fnds.cdk_constructs import compliance, pipeline_forge

from cdk.api_gateway import ApiGateway
from cdk.common_dlqs import CommonDeadLetterQueues
from cdk.core.alarms import Alarms
from cdk.core.cloudwatch import CloudWatch
from cdk.deployment_tests import DeploymentTests
from cdk.dynamodb import Dynamodb
from cdk.eventbridge import Eventbridge
from cdk.lambdas import Lambdas
from cdk.stack_inputs import StackInputs
from cdk.step_functions import StepFunctions


class AppStack:
    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: StackInputs) -> None:
        # Apply automatic IL4 fixes for all of our resources
        compliance.Fixer.register(stack)

        # Custom Alarms
        cloudwatch = CloudWatch(stack, stack_inputs)
        alarms = Alarms(stack, stack_inputs, cloudwatch)

        # Create Dynamodb Table
        dynamodb = Dynamodb(stack)

        # Create Eventbridge Rules
        eventbridge = Eventbridge(stack, stack_inputs, cloudwatch)

        # Create a central set of dead letter queues for all of the tenant queues to point to
        common_dlqs = CommonDeadLetterQueues(stack, alarms)

        # Create Lambdas
        lambdas = Lambdas(stack, stack_inputs, dynamodb, eventbridge, cloudwatch, alarms, common_dlqs)

        # Create ApiGateway
        api_gateway = ApiGateway(stack,
                                 stack_inputs,
                                 lambdas,
                                 cloudwatch,
                                 openapi_filename='bb-foundations-connector.oas.yml',
                                 override_logical_id_gateway='ApiGateway11E7F47B',
                                 override_logical_id_deployment='ApiGatewayDeploymentStagelive4845B4F0')

        # Create Step Functions
        StepFunctions(stack, stack_inputs, lambdas, dynamodb)

        # Create a CloudWatch dashboard
        cloudwatch.create_dashboard()

        # Run deployment tests
        DeploymentTests(stack, stack_inputs, lambdas, dynamodb, api_gateway, alarms)
