from os import path
from typing import Optional, cast

import aws_cdk.aws_iam as iam
from aws_cdk.aws_apigateway import SpecRestApi, StageOptions
from aws_cdk.aws_lambda import Tracing
from bb_ent_data_services_shared.cdk.util import override_logical_id
from bb_fnds.cdk_constructs import api_gateway
from bb_fnds.cdk_constructs import pipeline_forge
from bb_fnds.cdk_constructs import service_discovery

from cdk.core.cloudwatch import CloudWatch
from cdk.core.stack_inputs import CoreStackInputs
from cdk.lambdas import Lambdas


class ApiGateway:
    api: SpecRestApi
    gateway_url: str

    def __init__(self,
                 stack: pipeline_forge.Stack,
                 stack_inputs: CoreStackInputs,
                 lambdas: Lambdas,
                 cloudwatch: CloudWatch,
                 *,
                 openapi_filename: str,
                 override_logical_id_gateway: Optional[str] = None,
                 override_logical_id_deployment: Optional[str] = None):
        self.stack = stack
        self.stack_inputs = stack_inputs

        service_discovery.Registration.map_local_to_proto()

        # Define the API Gateway
        rest_api = api_gateway.AuthSpecRestApi(
            stack,
            'ApiGateway',
            open_api_spec_path=path.join('openapi', openapi_filename),
            deploy_options=StageOptions(
                throttling_rate_limit=stack_inputs.api_gateway.throttling_rate_limit,
                throttling_burst_limit=stack_inputs.api_gateway.throttling_burst_limit,
            ),
            register_permission_and_context=False,
        )
        self.api = rest_api.api_gateway

        # Create an authorizer for ourselves
        authorizer = api_gateway.LambdaAuthorizer(
            stack,
            'LambdaAuthorizer',
            issuers=[api_gateway.IssuerType.REGISTRAR],
            enable_registrar_int=True,
            tracing=Tracing.ACTIVE,
        )
        rest_api.attach_lambda_authorizer(fn=authorizer.function,
                                          placeholder='RegistrarAuthorizer',
                                          authority_enabled=False)

        # Retain original logical IDs so legacy deployments don't break
        if override_logical_id_gateway:
            override_logical_id(self.api, override_logical_id_gateway)
        if override_logical_id_deployment:
            override_logical_id(self.api.deployment_stage, override_logical_id_deployment)

        alarms = cloudwatch.api_gateway_add_alarms(self.api)

        # Allow this API gateway to call any REST lambda from the current stack
        for rest_lambda in lambdas.rest_apis:
            # TODO: Replace this with rest_api.attach_lambda. This has not been done yet because attach_lambda does
            #  not respect the logical ID overrides we made previously, forcing us to deploy new aliases.
            rest_lambda.alias.add_permission('CallFromApiGateway',
                                             principal=cast(iam.IPrincipal,
                                                            iam.ServicePrincipal('apigateway.amazonaws.com')),
                                             action='lambda:InvokeFunction',
                                             source_arn=self.api.arn_for_execute_api())

            # Allow blue-green rollout to watch API Gateway
            if rest_lambda.deployment_group:
                for alarm in alarms:
                    rest_lambda.deployment_group.add_alarm(alarm)

        self.gateway_url = self.api.url_for_path('/')
