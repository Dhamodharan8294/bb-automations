import datetime
import json
import os
import re
from enum import Enum
from time import sleep
from uuid import uuid4

import boto3
import pytest
import requests
from bb_ent_data_services_shared.lambdas.logger import logger
from bb_ent_data_services_shared.tests.integration.signed_request import iam_authorizer
from botocore.exceptions import ClientError
from requests import Response

from common.data.queues import StepFunctionAction, get_status_and_retry_information
from common.dates import parse_iso8601_date
from tests.core import registrar

# Note: These tests do not work locally because local SAM doesn't support API Gateway authorizers. You can run them
# against your development stack, though.

private_endpoints_url = os.environ.get('PRIVATE_ENDPOINTS_URL')

dynamodb = boto3.resource('dynamodb')
table_name = os.environ['TABLE_NAME']
table = dynamodb.Table(table_name)

aws_credentials = boto3.session.Session().get_credentials()


class AuthType(Enum):
    NONE = 1
    IAM = 2
    TOKEN = 3


def test_endpoints_require_credentials():
    tenant_id = 'random-id'

    resp = call_get_queues(tenant_id, auth=AuthType.NONE)
    assert_status_code(resp, 403)

    resp = call_get_queues(tenant_id, auth=AuthType.TOKEN)
    assert_status_code(resp, 403)

    resp = call_get_queue(tenant_id, 'Inbound', auth=AuthType.NONE)
    assert_status_code(resp, 401)

    resp = call_delete_queues(tenant_id, auth=AuthType.NONE)
    assert_status_code(resp, 403)

    resp = call_delete_queues(tenant_id, auth=AuthType.TOKEN)
    assert_status_code(resp, 403)


def test_queue_management():
    # Generate a tenantId for our tests.
    tenant_id = str(uuid4())

    # Assert no queues exists
    get_queues(tenant_id, expected_queues=[])

    # The first time the tenant asks for either of their own queues, we create both inbound and outbound.
    # This can take several minutes.
    logger.info('creating queues for tenant %s', tenant_id)

    # Create the inbound queue
    inbound_with_credentials = get_queue(tenant_id, 'Inbound')
    # Get the outbound queue
    outbound_with_credentials = get_queue(tenant_id, 'Outbound')

    # Assert only a private inbound queue was created
    get_queues(tenant_id, expected_queues=[inbound_with_credentials])

    try:
        # Build an SQS event that simulates what Learn would send us
        mock_event = {
            'source': 'bb.foundations.connector',
            'detail-type': 'FoundationsConnectorPing',
            'detail': {
                'tenantId': tenant_id,
                'test': True,
            },
            'time': '2019-07-15T23:28:33.359Z',
        }

        # Outbound Queue
        # We can send messages to this queue. This will call our SQS to Eventbridge function.
        message_send(outbound_with_credentials, mock_event)
        # Assert we cant receive messages
        with pytest.raises(ClientError):
            message_receive(outbound_with_credentials)

        # Inbound Queue
        # Assert we cant publish messages
        with pytest.raises(ClientError):
            message_send(inbound_with_credentials, mock_event)

        # Because we have a subscription to FoundationsConnectorPing, our EventBridge to SQS function should have
        # copied the sent message above over to the inbound queue. This might take some seconds so we wait.
        messages = poll_for_messages(inbound_with_credentials)
        assert len(messages['Messages']) == 1
        message_delete(inbound_with_credentials, messages['Messages'][0])

        body = json.loads(messages['Messages'][0]['Body'])
        assert body['source'] == mock_event['source']
        assert body['detail-type'] == mock_event['detail-type']
        assert body['detail'] == mock_event['detail']

    finally:
        # Wait for the create step function to be fully complete before we attempt to delete. Even though queues were
        # returned above, it's possible alarms were still being wired up. If we delete before create finishes,
        # this will look like a failed create, and calling get_queue again will trigger a recreate.
        wait_for_create_step_function(tenant_id)

        # Delete the tenant's queues
        delete_queues(tenant_id)

    # Validate queue no longer exists
    verify_delete(tenant_id)

    # Asking for deleted queue should not recreate
    resp = call_get_queue(tenant_id, 'Inbound')
    assert_status_code(resp, 404)


def get_queues(tenant_id, expected_queues):
    resp = call_get_queues(tenant_id)
    if expected_queues:
        assert_status_code(resp, 200)

        body = resp.json()
        assert set(body.keys()) == {'results'}

        expected = [queue_without_credentials(q) for q in expected_queues]
        assert body['results'] == expected

    else:
        assert_status_code(resp, 404)
        assert resp.json() == {
            'code': 404,
            'details': f"No queues exist for tenant '{tenant_id}'",
            'message': 'Queues not found'
        }


def queue_without_credentials(queue):
    return {
        'tenantId': queue['tenantId'],
        'type': queue['type'],
        'arn': queue['arn'],
        'url': queue['url'],
    }


def get_queue(tenant_id, queue_type, attempts=0):
    time_now = datetime.datetime.now(datetime.timezone.utc)

    resp = call_get_queue(tenant_id, queue_type)
    if attempts < 60 and resp.status_code == 202:
        sleep(10)
        return get_queue(tenant_id, queue_type, (attempts + 1))

    assert_status_code(resp, 200)
    queue = resp.json()

    assert queue['tenantId'] == tenant_id
    assert queue['type'] == queue_type
    assert queue['region'] == 'us-east-1'

    # Validate string is in AWS SQS Format
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-sqs-queues.html
    # arn:aws:sqs:region:account-id:resource
    assert re.match(r'arn:aws:sqs:[a-zA-Z0-9-]+:(\d)+:[a-zA-Z0-9-]+', queue['arn'])
    assert 'us-east-1' in queue['arn']
    if queue_type == 'Inbound':
        assert tenant_id in queue['arn']
    else:
        assert not tenant_id in queue['arn']
    assert queue_type.lower() in queue['arn']

    assert re.match(r'https://sqs.us-east-1.amazonaws.com/(\d)+/[a-zA-Z0-9-]+', queue['url'])
    if queue_type == 'Inbound':
        assert tenant_id in queue['url']
    else:
        assert not tenant_id in queue['url']
    assert queue_type.lower() in queue['url']

    # TODO: Is there anything useful we can assert for these?
    credentials = queue['credentials']
    assert credentials['accessKeyId']
    assert credentials['secretAccessKey']
    assert credentials['sessionToken']

    # Has to be a a maximum of an hour due to role chaining restraints
    expiry = parse_iso8601_date(credentials['expires'])
    assert expiry >= (time_now + datetime.timedelta(minutes=59))
    assert expiry <= (time_now + datetime.timedelta(minutes=61))

    # Ensure no unexpected attributes were returned
    assert set(queue.keys()) == {'tenantId', 'type', 'arn', 'url', 'region', 'credentials'}
    assert set(credentials.keys()) == {'accessKeyId', 'secretAccessKey', 'sessionToken', 'expires'}

    return queue


def delete_queues(tenant_id):
    resp = call_delete_queues(tenant_id)
    assert_status_code(resp, 202)


def verify_delete(tenant_id, attempts=0):
    resp = call_get_queues(tenant_id)
    # Check for 200 also due race condition where delete status has not yet been inserted
    if attempts < 20 and resp.status_code in (410, 200):
        sleep(10)
        return verify_delete(tenant_id, (attempts + 1))
    assert_status_code(resp, 404)
    return None


def delete_queue_messages(queue):
    messages = message_receive(queue)
    if 'Messages' in messages:
        for message in messages['Messages']:
            message_delete(queue, message)


def call_get_queues(tenant_id, auth: AuthType = AuthType.IAM):
    url = f'{private_endpoints_url}/internal/api/v1/foundationsConnector/tenants/{tenant_id}/queues'
    auth_headers = build_auth_headers(url, auth)
    return requests.get(url=url, auth=auth_headers)


def call_get_queue(tenant_id, queue_type, auth: AuthType = AuthType.TOKEN):
    url = f'{private_endpoints_url}/api/v1/foundationsConnector/tenants/{tenant_id}/queues/{queue_type}'
    auth_headers = build_auth_headers(url, auth)
    return requests.get(url=url, auth=auth_headers)


def call_delete_queues(tenant_id, auth: AuthType = AuthType.IAM):
    url = f'{private_endpoints_url}/internal/api/v1/foundationsConnector/tenants/{tenant_id}/queues'
    auth_headers = build_auth_headers(url, auth)
    return requests.delete(url=url, auth=auth_headers)


def build_auth_headers(url, auth_type):
    if auth_type == AuthType.TOKEN:
        return registrar.Authorizer()
    if auth_type == AuthType.IAM:
        return iam_authorizer(url)
    return {}


def message_send(queue, message):
    client = get_sqs_client(queue)
    client.send_message(
        QueueUrl=queue['url'],
        MessageBody=json.dumps(message),
    )


def message_receive(queue):
    logger.info('attempting to receive from %s', queue['url'])
    client = get_sqs_client(queue)
    return client.receive_message(
        QueueUrl=queue['url'],
        WaitTimeSeconds=20,
    )


def poll_for_messages(queue):
    attempts = 0
    while attempts < 7:
        messages = message_receive(queue)
        if 'Messages' in messages:
            return messages

        attempts += 1
    return None


def message_delete(queue, message):
    client = get_sqs_client(queue)
    client.delete_message(
        QueueUrl=queue['url'],
        ReceiptHandle=message['ReceiptHandle'],
    )


def get_sqs_client(queue):
    return boto3.client(
        'sqs',
        aws_access_key_id=queue['credentials']['accessKeyId'],
        aws_secret_access_key=queue['credentials']['secretAccessKey'],
        aws_session_token=queue['credentials']['sessionToken'],
        region_name=queue['region'],
    )


def build_sqs_test_event(tenant_id: str):
    """
    An SQS event that simulates what Learn would send us.
    """
    return {
        "source": "bb.foundations.connector",
        "detail-type": "FoundationsConnectorPing",
        "detail": {
            "tenantId": tenant_id,
            "test": True,
        },
        "time": "2019-07-15T23:28:33.359Z"
    }


def wait_for_create_step_function(tenant_id: str):
    attempts = 0
    while True:
        audit_info = get_status_and_retry_information(table, tenant_id=tenant_id, action=StepFunctionAction.CREATE)
        if audit_info.status == "Success":
            return

        attempts += 1
        if attempts > 10:
            assert audit_info.status == "Success"
        else:
            sleep(10)


def assert_status_code(resp: Response, expected_status_code: int):
    assert resp.status_code == expected_status_code, 'Incorrect status code. Response headers:\n' + str(
        resp.headers) + '\nResponse json:\n' + str(resp.json())
