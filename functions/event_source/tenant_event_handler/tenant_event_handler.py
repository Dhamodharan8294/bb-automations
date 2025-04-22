import os

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger

from common.core.event.simple_bridge_event_handler import SimpleBridgeEventHandler
from common.data.queues import StepFunctionAction, delete_queues, get_queues, get_status

xray_tracer = Tracer()

TENANT_DELETE_ARN = os.environ['TENANT_DELETE_ARN']
TABLE_NAME = os.environ['TABLE_NAME']

sfn_client = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(TABLE_NAME)


class TenantEventHandler(SimpleBridgeEventHandler):
    def handle_event(self, *, event_id: str, source: str, detail_type: str, event_detail: dict) -> None:
        if detail_type != 'Tenant Deleted':
            logger.warning('%s: Unexpected event type, dropping event source=%s, detail_type=%s, detail=%s', event_id,
                           source, detail_type, event_detail)
            return

        tenant_id = event_detail.get('id')
        if not tenant_id:
            logger.warning('%s: Received delete without a tenantId, dropping event source=%s, detail=%s', event_id,
                           source, event_detail)
            return

        if len(get_queues(table, tenant_id)) == 0:
            logger.info('%s: No queues found, nothing to delete for tenant %s', event_id, tenant_id)
            return

        if get_status(table, tenant_id, StepFunctionAction.DELETE) == 'Started':
            logger.info('%s: Queues are already being deleted for tenant %s', event_id, tenant_id)
            return

        logger.warning('%s, Deleting queues for tenant %s', event_id, tenant_id)
        delete_queues(sfn_client, TENANT_DELETE_ARN, tenant_id=tenant_id)


event_handler: TenantEventHandler = TenantEventHandler()


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context(correlation_id_path=correlation_paths.EVENT_BRIDGE)
def handler(event: dict, _context: LambdaContext):
    return event_handler.lambda_handler(event)
