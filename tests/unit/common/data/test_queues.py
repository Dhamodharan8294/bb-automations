from unittest.mock import patch, Mock, MagicMock
import json
import pytest

from common.data.queues import Queue, QueueType, item_to_queues, item_to_queue, get_sqs_credentials

TENANT_ID = "00000000-0000-0000-0000-000000000000"


def test_queue_type_to_string():
    assert QueueType.Inbound.name == 'Inbound'
    assert QueueType.Outbound.name == 'Outbound'


def test_queue_type_from_string():
    # direct mapping
    assert QueueType.from_string('Inbound') == QueueType.Inbound
    assert QueueType.from_string('Outbound') == QueueType.Outbound

    # case-insensitive
    assert QueueType.from_string('inBOUnd') == QueueType.Inbound
    assert QueueType.from_string('OUTboUnD') == QueueType.Outbound

    # unknown
    with pytest.raises(ValueError):
        QueueType.from_string('Unknown')


def test_item_to_queue():
    item_dict = {
        'InboundQueueArn': 'arn:inbound',
        'InboundQueueUrl': 'https://inbound',
        'OutboundQueueArn': 'arn:outbound',
        'OutboundQueueUrl': 'https://outbound',
        'CreatedAt': 'timestamp',
        'UpdatedAt': 'timestamp2'
    }

    expected_inbound = Queue(
        tenant_id=TENANT_ID,
        queue_type=QueueType.Inbound,
        sqs_arn=item_dict['InboundQueueArn'],
        url=item_dict['InboundQueueUrl'],
        created_date=item_dict['CreatedAt'],
        modified_date=item_dict['UpdatedAt'],
    )
    expected_outbound = Queue(
        tenant_id=TENANT_ID,
        queue_type=QueueType.Outbound,
        sqs_arn=item_dict['OutboundQueueArn'],
        url=item_dict['OutboundQueueUrl'],
        created_date=item_dict['CreatedAt'],
        modified_date=item_dict['UpdatedAt'],
    )

    assert item_to_queue(TENANT_ID, item_dict, QueueType.Inbound) == expected_inbound
    assert item_to_queue(TENANT_ID, item_dict, QueueType.Outbound) == expected_outbound

    del item_dict['OutboundQueueArn']
    del item_dict['OutboundQueueUrl']

    assert item_to_queue(TENANT_ID, item_dict, QueueType.Inbound) == expected_inbound
    assert item_to_queue(TENANT_ID, item_dict, QueueType.Outbound) is None


def test_item_to_queues():
    item_dict = {
        'InboundQueueArn': 'arn:inbound',
        'InboundQueueUrl': 'https://inbound',
        'OutboundQueueArn': 'arn:outbound',
        'OutboundQueueUrl': 'https://outbound',
        'CreatedAt': 'timestamp',
        'UpdatedAt': 'timestamp2'
    }
    expected_inbound = Queue(
        tenant_id=TENANT_ID,
        queue_type=QueueType.Inbound,
        sqs_arn=item_dict['InboundQueueArn'],
        url=item_dict['InboundQueueUrl'],
        created_date=item_dict['CreatedAt'],
        modified_date=item_dict['UpdatedAt'],
    )
    expected_outbound = Queue(
        tenant_id=TENANT_ID,
        queue_type=QueueType.Outbound,
        sqs_arn=item_dict['OutboundQueueArn'],
        url=item_dict['OutboundQueueUrl'],
        created_date=item_dict['CreatedAt'],
        modified_date=item_dict['UpdatedAt'],
    )

    assert item_to_queues(TENANT_ID, item_dict) == [expected_inbound, expected_outbound]

    del item_dict['OutboundQueueArn']
    del item_dict['OutboundQueueUrl']

    assert item_to_queues(TENANT_ID, item_dict) == [expected_inbound]


@patch('uuid.uuid4', lambda: '123456789')
def test_assume_sts_outbound():
    sts_client = Mock()
    sts_client.assume_role = MagicMock(return_value={
        'Credentials': {
            'AccessKeyId': '',
            'SecretAccessKey': '',
            'SessionToken': '',
            'Expiration': ''
        }
    })
    role = 'assumed_role'
    queue = Queue('b9600e2d-779d-46ae-b462-6d888e1f1761', QueueType.Outbound, 'shared_sqs_arn', 'shared_sqs_url', None,
                  None)
    legacy_queue = Queue('b9600e2d-779d-46ae-b462-6d888e1f1761', QueueType.Outbound, 'sqs_arn', 'sqs_url', None, None)
    get_sqs_credentials(sts_client, role, queue=queue, legacy_queue=legacy_queue)
    sts_client.assume_role.assert_called_once_with(
        RoleArn=role,
        RoleSessionName='b9600e2d-779d-46ae-b462-6d888e1f1761-outbound-12345678',
        DurationSeconds=3600,
        Policy=json.dumps({
            'Version': '2012-10-17',
            'Statement': [{
                'Effect': 'Allow',
                'Action': ['sqs:GetQueueAttributes', 'sqs:SendMessage'],
                'Resource': [
                    'shared_sqs_arn',
                    'sqs_arn',
                ],
            }]
        }),
    )


@patch('uuid.uuid4', lambda: '123456789')
def test_assume_sts_inbound():
    sts_client = Mock()
    sts_client.assume_role = MagicMock(return_value={
        'Credentials': {
            'AccessKeyId': '',
            'SecretAccessKey': '',
            'SessionToken': '',
            'Expiration': ''
        }
    })
    role = 'assumed_role'
    queue = Queue('b9600e2d-779d-46ae-b462-6d888e1f1761', QueueType.Inbound, 'sqs_arn', 'sqs_url', None, None)
    get_sqs_credentials(sts_client, role, queue=queue, legacy_queue=None)
    sts_client.assume_role.assert_called_once_with(
        RoleArn=role,
        RoleSessionName='b9600e2d-779d-46ae-b462-6d888e1f1761-inbound-12345678',
        DurationSeconds=3600,
        Policy=json.dumps({
            'Version': '2012-10-17',
            'Statement': [{
                'Effect': 'Allow',
                'Action': ['sqs:GetQueueAttributes', 'sqs:DeleteMessage', 'sqs:ReceiveMessage'],
                'Resource': [
                    'sqs_arn',
                ],
            }]
        }),
    )
