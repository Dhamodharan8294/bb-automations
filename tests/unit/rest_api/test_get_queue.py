# pylint: disable=import-outside-toplevel
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from requests_mock import ANY

from common.data.queues import AuditInformation, Queue, QueueType, SqsCredentials
from common.rest.constants import GET_QUEUE_MAX_RETRIES
from tests.common.core.mock_lambda_context import MockLambdaContext
from tests.unit.aws_mocks import apigw_event
from tests.unit.logging import assert_no_error_logs

REGION = 'us-east-1'
TENANT_ID = 'mock-tenant'


@pytest.fixture(autouse=True)
def aws_env_vars():
    os.environ['ASSUMABLE_SQS_ROLE'] = 'sqs-role-arn'
    os.environ['AWS_REGION'] = REGION
    os.environ['ALLOW_NON_SAAS_TENANTS'] = '1'
    os.environ['STACK_NAME'] = 'fnds-stack-name'
    os.environ['TABLE_NAME'] = 'bb-foundations-connector-table'
    os.environ['TENANT_PROVISIONER_ARN'] = 'provisioner_arn'
    os.environ['OUTBOUND_QUEUE_ARN'] = 'outbound_queue_arn'
    os.environ['OUTBOUND_QUEUE_URL'] = 'https://outbound_queue'
    # Because the service discovery DNS entry does not change, it is hopefully safe to hard-code it within this test
    os.environ['TENANT_DISCOVERY_HOST'] = 'tenancy-tenant-api-int-us-east-1-616d03.int.sd.bb-fnds.com.'


@patch('rest_api.get_queue.get_queue.get_tenant')
@patch('rest_api.get_queue.get_queue.get_sqs_credentials')
@patch('rest_api.get_queue.get_queue.get_shared_outbound_queue')
@patch('rest_api.get_queue.get_queue.get_queue')
def test_handler_queues_exist(mock_get_queue, mock_get_shared_outbound_queue, mock_get_sqs_credentials, mock_get_tenant,
                              caplog):
    from rest_api.get_queue import get_queue

    mock_get_tenant.return_value = {}

    legacy_queue = create_tenant_queue(TENANT_ID, QueueType.Outbound)
    mock_get_queue.return_value = legacy_queue

    queue = create_shared_queue(TENANT_ID, QueueType.Outbound)
    mock_get_shared_outbound_queue.return_value = queue

    credentials = create_credentials()
    mock_get_sqs_credentials.return_value = credentials

    event = apigw_event(tenant_id=TENANT_ID, queue_type='Outbound')
    response = get_queue.handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_get_queue.assert_called_once_with(get_queue.table, tenant_id=TENANT_ID, queue_type=QueueType.Outbound)
    mock_get_sqs_credentials.assert_called_once_with(get_queue.sts_client,
                                                     'sqs-role-arn',
                                                     queue,
                                                     legacy_queue=legacy_queue)

    assert response['statusCode'] == 200

    body = json.loads(response['body'])
    assert body == {
        'tenantId': TENANT_ID,
        'type': 'Outbound',
        'arn': queue.sqs_arn,
        'url': queue.url,
        'region': REGION,
        'credentials': {
            'accessKeyId': credentials.access_key_id,
            'secretAccessKey': credentials.secret_access_key,
            'sessionToken': credentials.session_token,
            'expires': "2020-06-01T00:00:00.000Z"
        }
    }


def test_handler_invalid_queue_type():
    from rest_api.get_queue import get_queue

    event = apigw_event(tenant_id=TENANT_ID, queue_type='asdf')
    response = get_queue.handler(event, MockLambdaContext())

    assert response['statusCode'] == 400

    body = json.loads(response['body'])
    assert body == {
        'code': 400,
        'message': 'Failed to parse queueType',
        'details': 'Unknown queue_type: asdf',
    }


@patch('rest_api.get_queue.get_queue.get_tenant')
@patch('rest_api.get_queue.get_queue.get_sqs_credentials')
@patch('rest_api.get_queue.get_queue.get_queue', return_value=None)
@patch('rest_api.get_queue.get_queue.get_status_and_retry_information', return_value=AuditInformation(status="Started"))
def test_handler_queues_creating(_mock_get_status_and_retry_information, _mock_get_queue, mock_get_sqs_credentials,
                                 mock_get_tenant):
    from rest_api.get_queue import get_queue

    mock_get_tenant.return_value = {}

    event = apigw_event(tenant_id=TENANT_ID, queue_type='Inbound')
    response = get_queue.handler(event, MockLambdaContext())

    mock_get_sqs_credentials.assert_not_called()

    assert response['statusCode'] == 202


@patch('rest_api.get_queue.get_queue.get_tenant')
@patch('rest_api.get_queue.get_queue.get_sqs_credentials')
@patch('rest_api.get_queue.get_queue.get_queue', return_value=None)
@patch('rest_api.get_queue.get_queue.get_status_and_retry_information',
       return_value=AuditInformation(status="Failure", retry_count=1, updated=datetime.now() - timedelta(minutes=1)))
@patch('rest_api.get_queue.get_queue.create_queues')
def test_handler_queues_create_failed_once_retry_time_not_passed(_mock_create_queues,
                                                                 _mock_get_status_and_retry_information,
                                                                 _mock_get_queue, mock_get_sqs_credentials,
                                                                 mock_get_tenant):
    from rest_api.get_queue import get_queue

    mock_get_tenant.return_value = {}

    event = apigw_event(tenant_id=TENANT_ID, queue_type='Inbound')
    response = get_queue.handler(event, MockLambdaContext())

    mock_get_sqs_credentials.assert_not_called()

    assert response['statusCode'] == 202


@patch('rest_api.get_queue.get_queue.get_tenant')
@patch('rest_api.get_queue.get_queue.get_sqs_credentials')
@patch('rest_api.get_queue.get_queue.get_queue', return_value=None)
@patch('rest_api.get_queue.get_queue.get_status_and_retry_information',
       return_value=AuditInformation(status="Failure", retry_count=1, updated=datetime.now() - timedelta(minutes=20)))
@patch('rest_api.get_queue.get_queue.create_queues')
def test_handler_queues_create_failed_once_retry_time_has_passed(mock_create_queues,
                                                                 _mock_get_status_and_retry_information,
                                                                 _mock_get_queue, mock_get_sqs_credentials,
                                                                 mock_get_tenant):
    from rest_api.get_queue import get_queue

    mock_get_tenant.return_value = {}

    event = apigw_event(tenant_id=TENANT_ID, queue_type='Inbound')
    response = get_queue.handler(event, MockLambdaContext())

    mock_get_sqs_credentials.assert_not_called()
    mock_create_queues.assert_called_once_with(get_queue.sfn_client,
                                               'provisioner_arn',
                                               TENANT_ID,
                                               "Developer",
                                               retry_count=1)

    assert response['statusCode'] == 202


@patch('rest_api.get_queue.get_queue.get_sqs_credentials')
@patch('rest_api.get_queue.get_queue.get_queue', return_value=None)
@patch('rest_api.get_queue.get_queue.get_status_and_retry_information',
       return_value=AuditInformation(status="Failure", retry_count=GET_QUEUE_MAX_RETRIES, updated=datetime.now()))
def test_handler_queues_create_failed_no_more_retries(_mock_get_status_and_retry_information, _mock_get_queue,
                                                      mock_get_sqs_credentials):
    from rest_api.get_queue import get_queue

    event = apigw_event(tenant_id=TENANT_ID, queue_type='Inbound')
    response = get_queue.handler(event, MockLambdaContext())

    mock_get_sqs_credentials.assert_not_called()

    assert response['statusCode'] == 500


@patch('rest_api.get_queue.get_queue.get_tenant')
@patch('rest_api.get_queue.get_queue.get_sqs_credentials')
@patch('rest_api.get_queue.get_queue.get_queue', return_value=None)
@patch('rest_api.get_queue.get_queue.get_status_and_retry_information', return_value=AuditInformation())
@patch('rest_api.get_queue.get_queue.create_queues')
def test_handler_queues_create(mock_create_queues, _mock_get_status_and_retry_information, _mock_get_queue,
                               mock_get_sqs_credentials, mock_get_tenant):
    from rest_api.get_queue import get_queue

    mock_get_tenant.return_value = {}

    event = apigw_event(tenant_id=TENANT_ID, queue_type='Inbound')
    response = get_queue.handler(event, MockLambdaContext())

    mock_get_sqs_credentials.assert_not_called()
    mock_create_queues.assert_called_once_with(get_queue.sfn_client, 'provisioner_arn', TENANT_ID, "Developer")

    assert response['statusCode'] == 202


@patch('rest_api.get_queue.get_queue.get_sqs_credentials')
@patch('rest_api.get_queue.get_queue.get_queue', return_value=None)
@patch('rest_api.get_queue.get_queue.get_status_and_retry_information', return_value=AuditInformation())
@patch('rest_api.get_queue.get_queue.create_queues')
def test_handler_tenant_api_failure(mock_create_queues, _mock_get_status_and_retry_information, _mock_get_queue,
                                    mock_get_sqs_credentials, requests_mock):
    from rest_api.get_queue import get_queue

    # Force the tenant API to be called
    get_queue.ALLOW_NON_SAAS_TENANTS = None
    get_queue.TENANT_API_URL = 'https://test-api-url'

    # Fake credentials for AWSV4Sign
    os.environ["AWS_ACCESS_KEY_ID"] = "mock_key_id"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "mock_secret"

    requests_mock.get(ANY, status_code=404)

    event = apigw_event(tenant_id=TENANT_ID, queue_type='Inbound')
    response = get_queue.handler(event, MockLambdaContext())

    assert response['statusCode'] == 404

    body = json.loads(response['body'])
    assert body == {
        'code': 404,
        'message': f'Tenant ID {TENANT_ID} not found in tenant service. Tenant API reason message: None',
    }

    mock_get_sqs_credentials.assert_not_called()
    mock_create_queues.assert_not_called()

    # Test with special config to skip tenant 404s
    get_queue.SKIP_TENANT_API_ERRORS = '1'

    response = get_queue.handler(event, MockLambdaContext())

    assert response['statusCode'] == 202
    mock_get_sqs_credentials.assert_not_called()
    mock_create_queues.assert_called_once_with(get_queue.sfn_client, 'provisioner_arn', TENANT_ID, 'Missing')


def create_tenant_queue(tenant_id: str, queue_type: QueueType):
    return create_queue(tenant_id, queue_type, resource_id=f'tenant-{tenant_id}-queue')


def create_shared_queue(tenant_id: str, queue_type: QueueType):
    return create_queue(tenant_id, queue_type, resource_id='shared-queue')


def create_queue(tenant_id: str, queue_type: QueueType, resource_id: str):
    sqs_arn = f'arn:aws:sqs:us-east-1:0123456789:{resource_id}'
    url = f'https://sqs.us-east-1.amazonaws.com/0123456789/{resource_id}'
    create_date = "2020-06-01 10:45:37 GMT-05:00"
    return Queue(queue_type=queue_type,
                 sqs_arn=sqs_arn,
                 url=url,
                 created_date=create_date,
                 modified_date=create_date,
                 tenant_id=tenant_id)


def create_credentials():
    return SqsCredentials(access_key_id='todo-key-id',
                          secret_access_key='todo-secret',
                          session_token='todo-session',
                          expires=datetime(2020, 6, 1, tzinfo=timezone.utc))
