# pylint: disable=import-outside-toplevel
import os
from unittest.mock import patch

import pytest

from tests.common.core.mock_lambda_context import MockLambdaContext
from tests.unit.aws_mocks import apigw_event
from tests.unit.logging import assert_no_error_logs

TENANT_ID = 'mock-tenant'


@pytest.fixture(autouse=True)
def aws_env_vars():
    os.environ['TABLE_NAME'] = 'bb-foundations-connector-table'
    os.environ['STACK_NAME'] = 'fnds-stack-name'
    os.environ['TENANT_DELETE_ARN'] = 'delete_arn'


@patch('rest_api.delete_queues.delete_queues.delete_queues')
@patch('rest_api.delete_queues.delete_queues.get_queues', return_value=["queue1", "queue2"])
@patch('rest_api.delete_queues.delete_queues.get_status', return_value=None)
def test_handler_queues_exist(_get_status, _get_queues, mock_delete_queues, caplog):
    from rest_api.delete_queues import delete_queues

    event = apigw_event(tenant_id=TENANT_ID)
    response = delete_queues.handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_delete_queues.assert_called_once_with(delete_queues.sfn_client, 'delete_arn', tenant_id=TENANT_ID)

    assert response == {
        'statusCode': 202
    }


@patch('rest_api.delete_queues.delete_queues.delete_queues')
@patch('rest_api.delete_queues.delete_queues.get_queues', return_value=[])
@patch('rest_api.delete_queues.delete_queues.get_status', return_value=None)
def test_handler_no_queues(_get_status, _get_queues, mock_delete_queues, caplog):
    from rest_api.delete_queues import delete_queues

    event = apigw_event(tenant_id=TENANT_ID)
    response = delete_queues.handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_delete_queues.assert_not_called()

    assert response == {
        'statusCode': 404
    }


@patch('rest_api.delete_queues.delete_queues.delete_queues')
@patch('rest_api.delete_queues.delete_queues.get_queues', return_value=["queue1", "queue2"])
@patch('rest_api.delete_queues.delete_queues.get_status', return_value="Started")
def test_handler_queues_deleting(_get_status, _get_queues, mock_delete_queues, caplog):
    from rest_api.delete_queues import delete_queues

    event = apigw_event(tenant_id=TENANT_ID)
    response = delete_queues.handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_delete_queues.assert_not_called()

    assert response == {
        'statusCode': 410
    }
