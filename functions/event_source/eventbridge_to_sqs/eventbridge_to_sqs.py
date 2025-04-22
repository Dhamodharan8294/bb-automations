import json
import os
import re
from typing import MutableMapping, cast

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger
from cachetools import TTLCache

from common.data.queues import Queue, QueueType, StepFunctionAction, get_queue, get_status_and_retry_information

xray_tracer = Tracer()

sqs_client = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']
table = dynamodb.Table(TABLE_NAME)

queue_cache: MutableMapping[str, Queue] = TTLCache(maxsize=256, ttl=300)
events_ignored_when_queue_missing = cast(dict[str, list[str]],
                                         json.loads(os.getenv('EVENTS_IGNORED_WHEN_QUEUE_MISSING', '{}')))


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context(correlation_id_path=correlation_paths.EVENT_BRIDGE)
def handler(event: dict, _context: LambdaContext):
    logger.debug('Received event: %s', event)

    if 'detail' in event:
        # A single message from EventBridge. This is the default behaviour.
        logger.debug('Handling EventBridge event')
        _handle_eventbridge_event(event)
    elif 'Records' in event:
        # A batch of messages being replayed from dead-letter queue. This will not be called automatically, but can be
        # triggered by manually creating an event-source-mapping linking the DLQ to the Lambda.
        logger.info('Handling batch of SQS events')
        _handle_sqs_events(event)
    else:
        raise Exception(f"Can't handle event {event}")


def _handle_eventbridge_event(event):
    # Look for the tenantId to know which SQS to forward the message to.
    detail = event['detail']
    tenant_id = detail.get('tenantId') or \
                detail.get('OldImage', {}).get('tenantId') or \
                detail.get('NewImage', {}).get('tenantId')
    if not tenant_id:
        raise RuntimeError('No tenantId is associated to the event')

    # Obtain the queue to which the event should be sent.
    queue = _get_tenant_queue(tenant_id)

    # No queue exists actually.
    if not queue:
        if _is_tenant_queue_deleted(tenant_id):
            # Tenant is in the process of being deleted, drop the event.
            logger.info('Dropping event for deleted tenant %s', tenant_id)
            return

        if _can_ignore_event_when_queue_missing(tenant_id, event):
            return

        raise RuntimeError(f'No queue with tenant {tenant_id} and type {QueueType.Inbound.name} exists')

    # Queue exists then send the message to that queue.
    try:
        sqs_client.send_message(QueueUrl=queue.url, MessageBody=json.dumps(event))
    except:
        # Remove queue from the cache just in case
        logger.info('Removing cached queue for %s', tenant_id)
        try:
            del queue_cache[tenant_id]
        except KeyError:
            pass

        if _is_tenant_queue_deleted(tenant_id):
            # The queue was deleted after we cached it
            logger.info('Dropping event for deleted tenant %s', tenant_id)
            return

        # Unknown failure
        raise


def _get_tenant_queue(tenant_id: str):
    if tenant_id in queue_cache:
        logger.info('Returning cached queue for %s', tenant_id)
        return queue_cache[tenant_id]

    queue = get_queue(table, tenant_id=tenant_id, queue_type=QueueType.Inbound)
    if queue:
        queue_cache[tenant_id] = queue

    return queue


def _is_tenant_queue_deleted(tenant_id: str) -> bool:
    audit_info = get_status_and_retry_information(table, tenant_id=tenant_id, action=StepFunctionAction.DELETE)
    # If the status field is set, the tenant has been deleted
    return bool(audit_info.status)


def _handle_sqs_events(event):
    failed_records = []
    for record in event['Records']:
        body = json.loads(record['body'])
        try:
            _handle_eventbridge_event(body)
        except:  # pylint: disable=bare-except
            failed_records.append(record['receiptHandle'])
            logger.exception('Failed replaying event: %s', body)

    # If some events failed, delete the successful ones
    if failed_records:
        # All records come from the same source queue
        first_record = event['Records'][0]
        queue_name = re.sub(r'.*:', '', first_record['eventSourceARN'])
        queue_url = sqs_client.get_queue_url(QueueName=queue_name)['QueueUrl']
        logger.debug('Extracted queue_url %s', queue_url)

        _delete_messages_from_sqs(queue_url, event['Records'], failed_records)

        raise RuntimeError('Failed to process one or more messages')


def _delete_messages_from_sqs(queue_url, all_records, failure_receipt_handles):
    success_receipt_handles = [
        record['receiptHandle'] for record in all_records if record['receiptHandle'] not in failure_receipt_handles
    ]
    if success_receipt_handles:
        sqs_client.delete_message_batch(QueueUrl=queue_url,
                                        Entries=[{
                                            'Id': f'handle-{i}',
                                            'ReceiptHandle': handle
                                        } for i, handle in enumerate(success_receipt_handles)])


def _can_ignore_event_when_queue_missing(tenant_id: str, event: dict) -> bool:
    if events_ignored_when_queue_missing:
        source = event.get('source')
        detail_type = event.get('detail-type')
        if source and detail_type and detail_type in events_ignored_when_queue_missing.get(source, []):
            logger.info('Dropping event "%s:%s" for missing tenant %s', source, detail_type, tenant_id)
            return True
    return False
