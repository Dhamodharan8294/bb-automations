import json
import logging
import os
from unittest.mock import call, patch

import pytest

from common.data.queues import AuditInformation, QueueType
from tests.common.core.mock_lambda_context import MockLambdaContext
from tests.common.test_logger import DEFAULT_LOGGER_NAME
from tests.unit.logging import assert_no_error_logs
from tests.unit.mock_event import DetailFormat, mock_event_bridge_event
from tests.unit.mock_queue import mock_queue

TENANT_ID = "mock-tenant-id"


@pytest.fixture(autouse=True)
def aws_env_vars():
    os.environ['TABLE_NAME'] = 'bb-foundations-connector-table'


@pytest.fixture(autouse=True)
def reset_cache_after_test():
    # allow the test to run
    yield

    # reset the cache afterwards
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import queue_cache
    queue_cache.clear()


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.sqs_client.send_message')
def test_handler_success(mock_send_message, mock_get_queue, caplog):
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import handler, table
    event = mock_event_bridge_event(tenant_id=TENANT_ID)
    queue = mock_queue(tenant_id=TENANT_ID, queue_type=QueueType.Inbound)
    mock_get_queue.return_value = queue

    handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_get_queue.assert_called_once_with(table, tenant_id=TENANT_ID, queue_type=QueueType.Inbound)
    mock_send_message.assert_called_with(QueueUrl=queue.url, MessageBody=json.dumps(event))


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.sqs_client.send_message')
def test_handler_finding_tenant_in_detail(mock_send_message, mock_get_queue, caplog):
    event = mock_event_bridge_event(detail_format=DetailFormat.DETAIL_ONLY)
    _verify_tenant_found(mock_send_message, mock_get_queue, caplog, event, 'mock-tenant-id')


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.sqs_client.send_message')
def test_handler_finding_tenant_in_old_image(mock_send_message, mock_get_queue, caplog):
    event = mock_event_bridge_event(detail_format=DetailFormat.OLD_IMAGE_ONLY)
    _verify_tenant_found(mock_send_message, mock_get_queue, caplog, event, 'mock-tenant-id-in-old-image')


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.sqs_client.send_message')
def test_handler_finding_tenant_in_new_image(mock_send_message, mock_get_queue, caplog):
    event = mock_event_bridge_event(detail_format=DetailFormat.NEW_IMAGE_ONLY)
    _verify_tenant_found(mock_send_message, mock_get_queue, caplog, event, 'mock-tenant-id-in-new-image')


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.sqs_client.send_message')
def test_handler_finding_tenant_in_old_and_new_image(mock_send_message, mock_get_queue, caplog):
    event = mock_event_bridge_event(detail_format=DetailFormat.OLD_AND_NEW_IMAGE_ONLY)
    _verify_tenant_found(mock_send_message, mock_get_queue, caplog, event, 'mock-tenant-id-in-old-image')


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.sqs_client.send_message')
def test_handler_finding_tenant_in_old_and_new_image_with_detail(mock_send_message, mock_get_queue, caplog):
    event = mock_event_bridge_event(detail_format=DetailFormat.OLD_AND_NEW_IMAGE_WITH_DETAIL)
    _verify_tenant_found(mock_send_message, mock_get_queue, caplog, event, 'mock-tenant-id-in-detail')


def _verify_tenant_found(mock_send_message, mock_get_queue, caplog, event: dict, tenant_id: str):
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import handler, table
    queue = mock_queue(tenant_id=tenant_id, queue_type=QueueType.Inbound)
    mock_get_queue.return_value = queue

    handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_get_queue.assert_called_once_with(table, tenant_id=tenant_id, queue_type=QueueType.Inbound)
    mock_send_message.assert_called_with(QueueUrl=queue.url, MessageBody=json.dumps(event))


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_status_and_retry_information')
def test_handler_no_queue(mock_get_status, mock_get_queue):
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import handler
    event = mock_event_bridge_event(tenant_id=TENANT_ID)
    mock_get_queue.return_value = None
    mock_get_status.return_value = AuditInformation()

    with pytest.raises(RuntimeError) as runtime_error:
        handler(event, MockLambdaContext())

    assert str(runtime_error.value) == f'No queue with tenant {TENANT_ID} and type {QueueType.Inbound.name} exists'


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_status_and_retry_information')
def test_handler_no_queue_ok(mock_get_status, mock_get_queue, caplog):
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import handler, events_ignored_when_queue_missing

    # Verifies that we parse the configuration in environment correctly. See conftest.py.
    assert events_ignored_when_queue_missing['test-source-1'] == ['test-detail-type-1', 'test-detail-type-2']
    assert events_ignored_when_queue_missing['test-source-2'] == ['test-detail-type-1', 'test-detail-type-2']

    mock_get_queue.return_value = None
    mock_get_status.return_value = AuditInformation()

    test_source = 'test-source-2'
    test_detail_type = 'test-detail-type-2'
    event = mock_event_bridge_event(tenant_id=TENANT_ID, source=test_source, detail_type=test_detail_type)

    # Verifies that events are ignored when queues are missing for such events.
    handler(event, MockLambdaContext())
    assert caplog.record_tuples == [
        (DEFAULT_LOGGER_NAME, logging.INFO,
         f'Dropping event "{test_source}:{test_detail_type}" for missing tenant {TENANT_ID}')
    ]


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_status_and_retry_information')
def test_handler_no_queue_deleted(mock_get_status, mock_get_queue, caplog):
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import handler
    event = mock_event_bridge_event(tenant_id=TENANT_ID)
    mock_get_queue.return_value = None
    mock_get_status.return_value = AuditInformation(status='Started')

    handler(event, MockLambdaContext())

    assert caplog.record_tuples == [(DEFAULT_LOGGER_NAME, logging.INFO,
                                     f'Dropping event for deleted tenant {TENANT_ID}')]


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
def test_handler_no_tenant(mock_get_queue):
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import handler
    event = mock_event_bridge_event(tenant_id=None)
    mock_get_queue.return_value = None

    with pytest.raises(RuntimeError) as runtime_error:
        handler(event, MockLambdaContext())

    assert str(runtime_error.value) == 'No tenantId is associated to the event'


@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.get_queue')
@patch('event_source.eventbridge_to_sqs.eventbridge_to_sqs.sqs_client.send_message')
def test_handler_sqs_success(mock_send_message, mock_get_queue, caplog):
    from event_source.eventbridge_to_sqs.eventbridge_to_sqs import handler, table

    eventbridge_events = [
        mock_event_bridge_event(tenant_id=TENANT_ID),
        mock_event_bridge_event(tenant_id='alternate-tenant'),
        mock_event_bridge_event(tenant_id=TENANT_ID),
    ]
    for i, eb_event in enumerate(eventbridge_events):
        eb_event['id'] = f'event-{i}'

    event = {
        'Records': [{
            'receiptHandle': f'handle-{i}',
            'body': json.dumps(eb_event),
            'eventSourceARN': 'arn:aws:sqs:us-east-1:257597320193:fnds-connector-test-dlq',
        } for i, eb_event in enumerate(eventbridge_events)]
    }

    queue = mock_queue(tenant_id=TENANT_ID, queue_type=QueueType.Inbound)
    mock_get_queue.return_value = queue

    handler(event, MockLambdaContext())

    assert_no_error_logs(caplog)
    mock_get_queue.assert_has_calls([
        call(table, tenant_id=TENANT_ID, queue_type=QueueType.Inbound),
        call(table, tenant_id='alternate-tenant', queue_type=QueueType.Inbound),
    ])
    assert mock_get_queue.call_count == 2
    mock_send_message.assert_has_calls(
        [call(QueueUrl=queue.url, MessageBody=json.dumps(eb_event)) for eb_event in eventbridge_events])
    assert mock_send_message.call_count == len(eventbridge_events)
