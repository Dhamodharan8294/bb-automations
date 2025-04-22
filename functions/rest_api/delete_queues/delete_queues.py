import os
from http import HTTPStatus

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger

from common.data.queues import StepFunctionAction, delete_queues, get_queues, get_status
from common.rest import RestApiWrapper, rest_response

xray_tracer = Tracer()

TENANT_DELETE_ARN = os.environ['TENANT_DELETE_ARN']
sfn_client = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']
table = dynamodb.Table(TABLE_NAME)


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@RestApiWrapper('rest_api.delete_queues')
def handler(event: dict, _context: LambdaContext):
    parameters = event['pathParameters']
    tenant_id = parameters['tenantId']

    if len(get_queues(table, tenant_id)) == 0:
        return rest_response(HTTPStatus.NOT_FOUND)

    if get_status(table, tenant_id, StepFunctionAction.DELETE) == "Started":
        return rest_response(HTTPStatus.GONE)

    logger.warning('Deleting queues for tenant %s', tenant_id)
    delete_queues(sfn_client, TENANT_DELETE_ARN, tenant_id=tenant_id)

    return rest_response(HTTPStatus.ACCEPTED)
