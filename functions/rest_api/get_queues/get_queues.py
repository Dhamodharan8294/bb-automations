import os
from http import HTTPStatus

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger

from common.data.queues import StepFunctionAction, get_queues, get_status
from common.rest import NotFound, RestApiWrapper, rest_response

xray_tracer = Tracer()

dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']
table = dynamodb.Table(TABLE_NAME)


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@RestApiWrapper('rest_api.get_queues')
def handler(event: dict, _context: LambdaContext):
    parameters = event['pathParameters']
    tenant_id = parameters['tenantId']

    queues = get_queues(table, tenant_id=tenant_id)

    if len(queues) == 0:
        raise NotFound('Queues not found', f"No queues exist for tenant '{tenant_id}'")

    if get_status(table, tenant_id, StepFunctionAction.DELETE) == "Started":
        return rest_response(HTTPStatus.GONE)

    json_queues = [to_json(queue) for queue in queues]
    return rest_response(HTTPStatus.OK, {
        'results': json_queues
    })


def to_json(queue):
    return {
        'tenantId': queue.tenant_id,
        'type': queue.queue_type.name,
        'arn': queue.sqs_arn,
        'url': queue.url
    }
