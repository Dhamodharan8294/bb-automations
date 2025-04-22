# pylint: disable=import-outside-toplevel
import json
import os
from unittest.mock import patch

import pytest

from tests.common.core.mock_lambda_context import MockLambdaContext
from tests.unit.aws_mocks import apigw_event
from tests.unit.logging import assert_no_error_logs
from tests.unit.mock_queue import mock_queues

TENANT_ID = 'mock-tenant'


@pytest.fixture(autouse=True)
def aws_env_vars():
    os.environ['TABLE_NAME'] = 'bb-foundations-connector-table'
    os.environ['STACK_NAME'] = 'fnds-stack-name'


@patch('rest_api.get_queues.get_queues.get_queues')
@patch('rest_api.get_queues.get_queues.get_status', return_value=None)
def test_handler_queues_exist(_mock_get_status, mock_get_queues, caplog):
    from rest_api.get_queues import get_queues

    inbound_queue, outbound_queue = mock_queues(inbound=True, outbound=True, tenant_id=TENANT_ID)

    queues = [inbound_queue, outbound_queue]
    mock_get_queues.return_value = queues

    event = apigw_event(tenant_id=TENANT_ID)
    response = get_queues.handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_get_queues.assert_called_once_with(get_queues.table, tenant_id=TENANT_ID)

    assert response['statusCode'] == 200

    body = json.loads(response['body'])
    assert body == {
        'results': [
            {
                'tenantId': TENANT_ID,
                'type': inbound_queue.queue_type.name,
                'arn': inbound_queue.sqs_arn,
                'url': inbound_queue.url,
            },
            {
                'tenantId': TENANT_ID,
                'type': outbound_queue.queue_type.name,
                'arn': outbound_queue.sqs_arn,
                'url': outbound_queue.url,
            },
        ]
    }


@patch('rest_api.get_queues.get_queues.get_queues')
@patch('rest_api.get_queues.get_queues.get_status', return_value='Started')
def test_handler_queues_deleting(_mock_get_status, mock_get_queues, caplog):
    from rest_api.get_queues import get_queues

    inbound_queue, outbound_queue = mock_queues(inbound=True, outbound=True, tenant_id=TENANT_ID)

    queues = [inbound_queue, outbound_queue]
    mock_get_queues.return_value = queues

    event = apigw_event(tenant_id=TENANT_ID)
    response = get_queues.handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    assert response['statusCode'] == 410


@patch('rest_api.get_queues.get_queues.get_queues', return_value=[])
def test_handler_not_found(_mock_get_queues):
    from rest_api.get_queues import get_queues

    event = apigw_event(tenant_id=TENANT_ID)
    response = get_queues.handler(event, MockLambdaContext())

    assert response['statusCode'] == 404

    body = json.loads(response['body'])
    assert body == {
        'code': 404,
        'message': 'Queues not found',
        'details': "No queues exist for tenant 'mock-tenant'",
    }
