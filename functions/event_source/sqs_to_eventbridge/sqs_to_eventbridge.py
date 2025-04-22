import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Optional

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger

from common.data.eventbridge import send_events_to_eventbridge
from common.dates import parse_iso8601_date

xray_tracer = Tracer()

STACK_NAME = os.environ['STACK_NAME']
EVENT_BUS = os.environ['EVENT_BUS']

eb_client = boto3.client('events')
sqs_client = boto3.client('sqs')


@dataclass
class Message:
    """
    A parsed SQS event from Learn.
    """
    lambda_arn: str
    queue_arn: str
    source: str
    detail_type: str
    detail: dict
    time: datetime
    sender_id: str

    def tenant_id(self):
        return self.detail.get('tenantId')

    def to_eventbridge(self):
        return {
            'Source': self.source,
            'DetailType': self.detail_type,
            'Detail': json.dumps(self.detail),
            'Time': self.time,
            'Resources': [self.lambda_arn, self.queue_arn],
            'EventBusName': EVENT_BUS
        }


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: dict, _context: LambdaContext):
    """ Entrypoint for the event source lambda """
    events = []
    failed_records = []

    queue_name = queue_name_from_queue_arn(stack_name=STACK_NAME, queue_arn=event['Records'][0]['eventSourceARN'])
    queue_url = get_sqs_url(queue_name)

    for record in event['Records']:
        message = parse_message(record, _context.invoked_function_arn)
        if message is None:
            # Message could not be parsed.
            failed_records.append(record['receiptHandle'])
            continue

        logger.info('Processing message sent by %s to queue %s', message.sender_id, message.queue_arn)
        if not validate_message(message):
            # Drop messages where tenant_id's don't match
            failed_records.append(record['receiptHandle'])
            continue

        events.append(message.to_eventbridge())

    if events:
        for error in send_events_to_eventbridge(eb_client, events):
            failed_records.append(error.event['receiptHandle'])
            logger.error('Failed sending event: %s \n to eventbridge with error: %s', error.event, error.error_message)

    # If some message failed to parse or be sent -> Delete the successful ones and raise an exception for retry logic.
    if failed_records:
        delete_messages_from_sqs(queue_url, event['Records'], failed_records)
        raise RuntimeError('Failed to process one or more messages')


def parse_message(record: dict, lambda_arn: str) -> Optional[Message]:
    """
    Parse the record and return a Message or None
    :param record: The raw record from sqs queue
    :param lambda_arn: The current Lambda function's ARN
    :return: Message or None
    """
    try:
        body = json.loads(record['body'])
        sender_id = record['attributes']['SenderId']
        return Message(lambda_arn=lambda_arn,
                       queue_arn=record['eventSourceARN'],
                       source=body['source'],
                       detail_type=body['detail-type'],
                       detail=body['detail'],
                       time=parse_iso8601_date(body['time']),
                       sender_id=sender_id)
    except ValueError:
        logger.exception('Could Not Parse Json %s', json.dumps(record))
        return None
    except KeyError:
        logger.exception('Message does not have required shape %s', json.dumps(record))
        return None


def validate_message(message: Message) -> bool:
    """
    Validate the record satisfies the requirements such as
    valid json body and correct tenantId
    :param message: Message from the queue
    :return: True or False
    """
    event_tenant = tenant_from_event_sender(message.sender_id)
    if message.tenant_id() != event_tenant:
        logger.error("TenantId %s does not match event sender's TenantId %s", message.tenant_id(), event_tenant)
        return False
    return True


def tenant_from_event_sender(sender_id: str):
    match = re.search('^[A-Z0-9]+:(.*)-(inbound|outbound)', sender_id)
    if not match:
        raise Exception(f'Tenant ID not found in {sender_id}')
    return match.group(1)


def queue_name_from_queue_arn(*, stack_name: str, queue_arn: str):
    match = re.search(f'{stack_name}(-.+)?-(inbound|outbound)', queue_arn)
    if not match:
        raise Exception(f'Queue name not found in {queue_arn}')
    return match.group(0)


@lru_cache
def get_sqs_url(queue_name: str):
    queue = sqs_client.get_queue_url(QueueName=queue_name)
    return queue['QueueUrl']


def delete_messages_from_sqs(queue_url, all_records, failure_receipt_handles):
    success_receipt_handles = [
        record['receiptHandle'] for record in all_records if record['receiptHandle'] not in failure_receipt_handles
    ]
    if success_receipt_handles:
        sqs_client.delete_message_batch(QueueUrl=queue_url,
                                        Entries=[{
                                            'Id': f'handle-{i}',
                                            'ReceiptHandle': handle
                                        } for i, handle in enumerate(success_receipt_handles)])
