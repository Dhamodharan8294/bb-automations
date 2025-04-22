import json
import os
from typing import Optional
from unittest.mock import patch

import pytest

from common.data.queues import QueueType, get_sqs_credential_id
from common.dates import parse_iso8601_date
from tests.common.core.mock_lambda_context import MockLambdaContext

LAMBDA_ARN = 'arn:aws:lambda:us-east-1:257597320193:function:fnds-connector-example-SqsToEventBridgeFunction'
TENANT_ID = 'd27e23ee-7953-472d-af70-b06e13b14eb3'


@pytest.fixture(autouse=True)
def env_vars():
    os.environ['STACK_NAME'] = 'fnds-connector'
    os.environ['EVENT_BUS'] = 'default'


def test_parse_message():
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge

    queue_arn = "arn:aws:sqs:us-east-2:123456789012:my-queue"
    source = 'my.source'
    detail_type = 'RandomEventType'
    detail = {
        'id': '123',
        'owner': 'Learn',
        'tenantId': TENANT_ID,
    }
    time = '2020-05-09T01:14:16.123Z'

    learn_event = {
        'source': source,
        'detail-type': detail_type,
        'detail': detail,
        'time': time,
        'ignored': 'extra field',
    }
    sqs_record = _create_learn_sqs_record(queue_arn, learn_event)

    message = sqs_to_eventbridge.parse_message(sqs_record, LAMBDA_ARN)
    assert message == sqs_to_eventbridge.Message(lambda_arn=LAMBDA_ARN,
                                                 queue_arn=queue_arn,
                                                 source=source,
                                                 detail_type=detail_type,
                                                 detail=detail,
                                                 time=parse_iso8601_date(time),
                                                 sender_id=message.sender_id)
    assert message.tenant_id() == TENANT_ID
    assert TENANT_ID in message.sender_id and TENANT_ID == sqs_to_eventbridge.tenant_from_event_sender(
        message.sender_id)


def test_parse_no_tenant_message():
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge
    queue_arn = "arn:aws:sqs:us-east-2:123456789012:my-queue"
    invalid_record = _create_tenantless_record(queue_arn)
    message = sqs_to_eventbridge.parse_message(invalid_record, LAMBDA_ARN)
    assert message.tenant_id() is None


def test_parse_invalid_json():
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge
    queue_arn = "arn:aws:sqs:us-east-2:123456789012:my-queue"
    invalid_json_record = _create_invalid_json_record(queue_arn)
    message = sqs_to_eventbridge.parse_message(invalid_json_record, LAMBDA_ARN)
    assert message is None


def test_tenant_from_event_sender():
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge

    tenant_id = 'a0ad577b-2601-4d98-b7be-9565e4e99508'
    sender_id = f'AROATX6P7FQA4E5D633O2:{tenant_id}-outbound-8b2ca18e'
    assert sqs_to_eventbridge.tenant_from_event_sender(sender_id) == tenant_id


def test_queue_name_from_queue_arn():
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge

    inbound_arn = 'arn:aws:sqs:us-east-2:123456789012:fnds-connector-b03a44c1-e299-41a7-8bc0-fed7ca42e271-inbound'
    legacy_outbound_arn = 'arn:aws:sqs:us-east-2:123456789012:fnds-connector-b03a44c1-e299-41a7-8bc0-fed7ca42e271-outbound'
    outbound_arn = 'arn:aws:sqs:us-east-2:123456789012:fnds-connector-outbound'
    malformed_arn = 'arn:aws:sqs:us-east-2:123456789012:malformed-queue'

    queue_name = sqs_to_eventbridge.queue_name_from_queue_arn(stack_name='fnds-connector', queue_arn=inbound_arn)
    assert queue_name == 'fnds-connector-b03a44c1-e299-41a7-8bc0-fed7ca42e271-inbound'
    queue_name = sqs_to_eventbridge.queue_name_from_queue_arn(stack_name='fnds-connector',
                                                              queue_arn=legacy_outbound_arn)
    assert queue_name == 'fnds-connector-b03a44c1-e299-41a7-8bc0-fed7ca42e271-outbound'
    queue_name = sqs_to_eventbridge.queue_name_from_queue_arn(stack_name='fnds-connector', queue_arn=outbound_arn)
    assert queue_name == 'fnds-connector-outbound'

    with pytest.raises(Exception):
        sqs_to_eventbridge.queue_name_from_queue_arn(stack_name='fnds-connector', queue_arn=malformed_arn)


def test_validate_message():
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge

    queue_arn = 'arn:aws:sqs:us-east-2:123456789012:my-queue'
    sqs_record = _create_valid_record(queue_arn, version=1)
    message = sqs_to_eventbridge.parse_message(sqs_record, LAMBDA_ARN)
    assert sqs_to_eventbridge.validate_message(message)

    # mismatched tenantid
    message.detail['tenantId'] = '00000000-0000-0000-000000000000'
    assert not sqs_to_eventbridge.validate_message(message)


@patch('event_source.sqs_to_eventbridge.sqs_to_eventbridge.send_events_to_eventbridge')
@patch('event_source.sqs_to_eventbridge.sqs_to_eventbridge.get_sqs_url')
def test_handler_good_records(mock_get_sqs_url, send_events_to_eventbridge):
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge
    queue_arn = 'arn:aws:sqs:us-east-2:123456789012:fnds-connector-d27e23ee-7953-472d-af70-b06e13b14eb3-outbound'
    queue_url = 'https://queue.amazonaws.com/123456789012/fnds-connector-d27e23ee-7953-472d-af70-b06e13b14eb3-outbound'
    mock_get_sqs_url.return_value = queue_url

    valid1 = _create_valid_record(queue_arn, version=1)
    valid2 = _create_valid_record(queue_arn, version=2)
    event = {
        'Records': [valid1, valid2]
    }
    context = MockLambdaContext(invoked_function_arn=LAMBDA_ARN)
    sqs_to_eventbridge.handler(event, context)

    expected_eb_event1 = _outgoing_eventbridge_event(queue_arn, version=1)
    expected_eb_event2 = _outgoing_eventbridge_event(queue_arn, version=2)
    send_events_to_eventbridge.assert_called_once_with(sqs_to_eventbridge.eb_client,
                                                       [expected_eb_event1, expected_eb_event2])


@patch('event_source.sqs_to_eventbridge.sqs_to_eventbridge.send_events_to_eventbridge')
@patch('event_source.sqs_to_eventbridge.sqs_to_eventbridge.delete_messages_from_sqs')
@patch('event_source.sqs_to_eventbridge.sqs_to_eventbridge.get_sqs_url')
def test_handler_with_some_bad_records(mock_get_sqs_url, mock_delete_messages_from_sqs, send_events_to_eventbridge):
    from event_source.sqs_to_eventbridge import sqs_to_eventbridge
    queue_arn = 'arn:aws:sqs:us-east-2:123456789012:fnds-connector-d27e23ee-7953-472d-af70-b06e13b14eb3-outbound'
    queue_url = 'https://queue.amazonaws.com/123456789012/fnds-connector-d27e23ee-7953-472d-af70-b06e13b14eb3-outbound'

    mock_get_sqs_url.return_value = queue_url

    valid1 = _create_valid_record(queue_arn, version=1)
    valid2 = _create_valid_record(queue_arn, version=2)
    tenantless = _create_tenantless_record(queue_arn)
    mismatching = _create_mismatching_record(queue_arn)
    invalid_json = _create_invalid_json_record(queue_arn)
    all_records = [valid1, tenantless, mismatching, invalid_json, valid2]
    bad_records = [tenantless, mismatching, invalid_json]
    with pytest.raises(RuntimeError) as runtime_error:
        event = {
            'Records': all_records
        }
        context = MockLambdaContext(invoked_function_arn=LAMBDA_ARN)
        sqs_to_eventbridge.handler(event, context)
    assert str(runtime_error.value) == 'Failed to process one or more messages'

    expected_eb_event1 = _outgoing_eventbridge_event(queue_arn, version=1)
    expected_eb_event2 = _outgoing_eventbridge_event(queue_arn, version=2)
    send_events_to_eventbridge.assert_called_once_with(sqs_to_eventbridge.eb_client,
                                                       [expected_eb_event1, expected_eb_event2])
    mock_delete_messages_from_sqs.assert_called_once_with(queue_url, all_records,
                                                          [record['receiptHandle'] for record in bad_records])


def _create_valid_record(queue_arn: str, version: int) -> dict:
    event = _event_from_learn(tenant_id=TENANT_ID, version=version)
    return _create_learn_sqs_record(queue_arn, event)


def _create_tenantless_record(queue_arn: str) -> dict:
    event = _event_from_learn()
    return _create_learn_sqs_record(queue_arn, event)


def _create_mismatching_record(queue_arn: str) -> dict:
    event = _event_from_learn(tenant_id='00000000-0000-0000-000000000000')
    return _create_learn_sqs_record(queue_arn, event)


def _create_invalid_json_record(queue_arn: str) -> dict:
    payload = '{ invalid json }'
    return _create_raw_sqs_record(payload, queue_arn)


def _create_learn_sqs_record(queue_arn: str, event: dict):
    """
    Wraps the specified Learn event in an SQS envelope.
    """
    payload = json.dumps(event)
    return _create_raw_sqs_record(payload, queue_arn)


def _create_raw_sqs_record(payload: str, queue_arn: str) -> dict:
    """
    Wraps the specified payload in an SQS envelope.
    """
    sender_id = f'AIDAIENQZJOLO23YVJ4VO:{get_sqs_credential_id(TENANT_ID, QueueType.Outbound)}'

    return {
        "messageId": "059f36b4-87a3-44ab-83d2-661975830a7d",
        "receiptHandle": "AQEBwJnKyrHigUMZj6rYigCgxlaS3SLy0a...",
        "body": payload,
        "attributes": {
            "ApproximateReceiveCount": "1",
            "SentTimestamp": "1545082649183",
            "SenderId": sender_id,
            "ApproximateFirstReceiveTimestamp": "1545082649185"
        },
        "messageAttributes": {},
        "md5OfBody": "e4e68fb7bd0e697a0ae8f1bb342846b3",
        "eventSource": "aws:sqs",
        "eventSourceARN": queue_arn,
        "awsRegion": "us-east-1"
    }


def _event_from_learn(tenant_id: Optional[str] = None, version: Optional[int] = 23) -> dict:
    """
    Generates an incoming event from Learn, not including an SQS envelope.
    """
    event: dict = {
        'source': 'learn.data.source',
        'detail-type': 'Update',
        'detail': {
            'id': '23253265-c53c-45c0-94c4-8df6a9d46c8b',
            'tenantId': tenant_id,
            'version': 23,
            'modified': '2020-05-08T00:26:34.123Z',
            'description': 'Spring 2020 term',
            'owner': 'Learn',
            'ids': {
                'pk1': '_123_1',
                'externalId': 'Spring2020'
            }
        },
        'time': '2020-05-09T01:14:16.000Z',
    }

    # inject event overrides
    if not tenant_id:
        del event['detail']['tenantId']
    if version:
        event['detail']['version'] = version

    return event


def _outgoing_eventbridge_event(queue_arn: str, version: int) -> dict:
    """
    Builds an outgoing EventBridge event based on the same template as the Learn event above.
    """
    event_detail = json.dumps({
        'id': '23253265-c53c-45c0-94c4-8df6a9d46c8b',
        'tenantId': TENANT_ID,
        'version': version,
        'modified': '2020-05-08T00:26:34.123Z',
        'description': 'Spring 2020 term',
        'owner': 'Learn',
        'ids': {
            'pk1': '_123_1',
            'externalId': 'Spring2020'
        }
    })
    return {
        'Source': 'learn.data.source',
        'DetailType': 'Update',
        'Detail': event_detail,
        'Time': (parse_iso8601_date('2020-05-09T01:14:16.000Z')),
        'Resources': [LAMBDA_ARN, queue_arn],
        'EventBusName': os.getenv('EVENT_BUS'),
    }
