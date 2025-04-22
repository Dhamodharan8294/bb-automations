import os
import typing
from unittest.mock import patch

import pytest

from common.data.queues import StepFunctionAction
from tests.common.core.mock_lambda_context import MockLambdaContext

TENANT_ID = 'mock-tenant'


@pytest.fixture(autouse=True)
def aws_env_vars():
    os.environ['TABLE_NAME'] = 'bb-foundations-connector-table'
    os.environ['STACK_NAME'] = 'fnds-stack-name'
    os.environ['TENANT_DELETE_ARN'] = 'delete_arn'


@patch('event_source.tenant_event_handler.tenant_event_handler.delete_queues')
@patch('event_source.tenant_event_handler.tenant_event_handler.get_queues', return_value=['outbound-queue'])
@patch('event_source.tenant_event_handler.tenant_event_handler.get_status', return_value=None)
def test_handler_success(_get_status, _get_queues, mock_delete_queues):
    from event_source.tenant_event_handler import tenant_event_handler

    event = _tenant_delete_event()
    tenant_event_handler.handler(event, MockLambdaContext())

    mock_delete_queues.assert_called_once_with(tenant_event_handler.sfn_client, 'delete_arn', tenant_id=TENANT_ID)


@patch('event_source.tenant_event_handler.tenant_event_handler.delete_queues')
@patch('event_source.tenant_event_handler.tenant_event_handler.get_queues', return_value=['outbound-queue'])
@patch('event_source.tenant_event_handler.tenant_event_handler.get_status', return_value=None)
def test_handler_wrong_detail_type(_get_status, _get_queues, mock_delete_queues):
    from event_source.tenant_event_handler import tenant_event_handler

    event = _tenant_delete_event(detail_type='Tenant Created')
    tenant_event_handler.handler(event, MockLambdaContext())

    mock_delete_queues.assert_not_called()


@patch('event_source.tenant_event_handler.tenant_event_handler.delete_queues')
@patch('event_source.tenant_event_handler.tenant_event_handler.get_queues', return_value=['outbound-queue'])
@patch('event_source.tenant_event_handler.tenant_event_handler.get_status', return_value=None)
def test_handler_event_missing_tenantid(_get_status, _get_queues, mock_delete_queues):
    from event_source.tenant_event_handler import tenant_event_handler

    event = _tenant_delete_event(tenant_id=None)
    tenant_event_handler.handler(event, MockLambdaContext())

    mock_delete_queues.assert_not_called()


@patch('event_source.tenant_event_handler.tenant_event_handler.delete_queues')
@patch('event_source.tenant_event_handler.tenant_event_handler.get_queues', return_value=[])
@patch('event_source.tenant_event_handler.tenant_event_handler.get_status', return_value=None)
def test_handler_queues_dont_exist(_get_status, _get_queues, mock_delete_queues):
    from event_source.tenant_event_handler import tenant_event_handler

    event = _tenant_delete_event()
    tenant_event_handler.handler(event, MockLambdaContext())

    mock_delete_queues.assert_not_called()


@patch('event_source.tenant_event_handler.tenant_event_handler.delete_queues')
@patch('event_source.tenant_event_handler.tenant_event_handler.get_queues', return_value=['outbound-queue'])
@patch('event_source.tenant_event_handler.tenant_event_handler.get_status', return_value='Started')
def test_handler_delete_already_scheduled(get_status, _get_queues, mock_delete_queues):
    from event_source.tenant_event_handler import tenant_event_handler

    event = _tenant_delete_event()
    tenant_event_handler.handler(event, MockLambdaContext())

    mock_delete_queues.assert_not_called()
    get_status.assert_called_with(tenant_event_handler.table, TENANT_ID, StepFunctionAction.DELETE)


def _tenant_delete_event(detail_type: str = 'Tenant Deleted', tenant_id: typing.Optional[str] = TENANT_ID):
    return {
        'version': '0',
        'id': '1a810e97-ec8a-b094-2170-035125fc560c',
        'detail-type': detail_type,
        'source': 'bb.tenant',
        'account': '257597320193',
        'time': '2020-10-14T19:29:35Z',
        'region': 'us-east-1',
        'resources': [],
        'detail': {
            'id': tenant_id
        }
    }
