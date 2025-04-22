import os

import aws_cdk.aws_codebuild as codebuild
import aws_cdk.aws_iam as iam
from bb_fnds.cdk_constructs import deployment_tests, pipeline_forge

from cdk.api_gateway import ApiGateway
from cdk.core.alarms import Alarms
from cdk.dynamodb import Dynamodb
from cdk.lambdas import Lambdas
from cdk.stack_inputs import StackInputs


class DeploymentTests:
    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: StackInputs, lambdas: Lambdas, dynamodb: Dynamodb,
                 api_gateway: ApiGateway, alarms: Alarms):

        if not stack_inputs.tests.enable_integ_rest_tests:
            return

        test_env = {
            k: codebuild.BuildEnvironmentVariable(value=v)
            for k, v in lambdas.common_env.items()
        }

        # Developer hook to skip execution without deleting the CodeBuild resources
        skip_execution = os.getenv('DEV_SKIP_DEPLOYMENT_TESTS') == '1' or stack.is_il4
        test_env["SKIP_EXECUTION"] = codebuild.BuildEnvironmentVariable(value=skip_execution)

        test_env["API_GATEWAY_URL"] = codebuild.BuildEnvironmentVariable(value=api_gateway.gateway_url)
        test_env["IS_IL4"] = codebuild.BuildEnvironmentVariable(value=str(stack.is_il4))

        tests = deployment_tests.CodeBuildDeploymentTests(
            stack,
            "DeploymentTests",
            depends_on=[stack],
            requirements_file=None if skip_execution else "deployment-tests-requirements.txt",
            code_build=codebuild.CommonProjectProps(environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0),
                                                    environment_variables=test_env),
            exclude=[
                'tests/report/**',
            ],
            rest_api_gateway=api_gateway.api)

        dynamodb.tenant_resources_table.grant_read_write_data(tests)

        # Allow tests to call the pyfnds Registrar token generator Lambda
        tests.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(resources=['*'], actions=['lambda:InvokeFunction']))

        # Ensure no alarms are created for the test infrastructure
        alarms.monitor.ignore_scope(tests)
