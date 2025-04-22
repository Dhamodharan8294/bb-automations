import os
from datetime import datetime
from typing import Optional

import boto3
import botocore
import requests
from aws_lambda_powertools import Tracer
from bb_ent_data_services_shared.lambdas.logger import logger

from common.dates import format_iso8601_date

xray_tracer = Tracer()

dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']
table = dynamodb.Table(TABLE_NAME)


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event, _context):
    """
    This function is a CloudFormation custom resource handler, which manages the tenant's DynamoDB metadata row.
    """
    logger.debug('In with: %s', event)

    try:
        request_type = event['RequestType']
        properties = event['ResourceProperties']
        tenant_id = properties['TenantId']

        logger.info('manage_metadata in with request_type=%s, tenant_id=%s', request_type, tenant_id)

        time_now = format_iso8601_date(datetime.now())
        key = {
            'pk': f'TENANT_ID#{tenant_id}',
            'sk': 'METADATA'
        }

        if request_type == 'Create':
            try:
                _create_metadata(key, properties, time_now)
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    raise

                # the metadata row already existed, probably from the old CDK template
                _update_metadata(key, properties, time_now)

        elif request_type == 'Update':
            _update_metadata(key, properties, time_now)

        elif request_type == 'Delete':
            _delete_metadata(key)

        _send_response(event, success=True)

    except BaseException as e:  # pylint: disable=broad-except
        logger.exception('Failed to process event')
        _send_response(event, success=False, reason=str(e))


def _create_metadata(key, properties, time_now):
    table.put_item(
        Item={
            **key,
            'ClientId': properties['ClientId'],
            'Version': properties['Version'],
            'InboundQueueArn': properties['InboundQueueArn'],
            'InboundQueueUrl': properties['InboundQueueUrl'],
            'CreatedAt': time_now,
            'UpdatedAt': time_now,
        },
        ConditionExpression='attribute_not_exists(pk) AND attribute_not_exists(sk)',
    )


def _update_metadata(key, properties, time_now):
    table.update_item(
        Key=key,
        UpdateExpression='SET ClientId = :clientId'
        ', Version = :version'
        ', InboundQueueArn = :inArn'
        ', InboundQueueUrl = :inUrl'
        ', UpdatedAt = :updatedAt'
        ' REMOVE OutboundQueueArn, OutboundQueueUrl',
        ExpressionAttributeValues={
            ':clientId': properties['ClientId'],
            ':version': properties['Version'],
            ':inArn': properties['InboundQueueArn'],
            ':inUrl': properties['InboundQueueUrl'],
            ':updatedAt': time_now,
        },
    )


def _delete_metadata(key):
    table.delete_item(Key=key)


def _send_response(event, *, success: bool, reason: Optional[str] = None):
    # See https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/crpg-ref-responses.html
    response_body = {
        'Status': 'SUCCESS' if success else 'FAILED',
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'PhysicalResourceId': 'DynamoRecord',
    }

    if reason:
        response_body['Reason'] = reason

    requests.put(event["ResponseURL"], json=response_body, timeout=10)
