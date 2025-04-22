from common.data.queues import Queue, QueueType

STACK_NAME = "fnds-connector-local"
REGION = 'us-east-1'


def mock_queue(tenant_id: str = "mock-tenant-id", queue_type: QueueType = QueueType.Inbound):
    queue_id = f'{STACK_NAME}-{tenant_id}-{queue_type.name}'
    return Queue(
        tenant_id=tenant_id,
        queue_type=queue_type,
        sqs_arn=f'arn:aws:sqs:{REGION}:257597320193:{queue_id}',
        url=f'https://queue.amazonaws.com/257597320193/{queue_id}',
        created_date="2020-07-15T17:09:06",
        modified_date="2020-07-15T17:09:06",
    )


def mock_queues(inbound: bool, outbound: bool, tenant_id: str = "mock-tenant-id"):
    inbound_queue = mock_queue(tenant_id=tenant_id, queue_type=QueueType.Inbound)
    outbound_queue = mock_queue(tenant_id=tenant_id, queue_type=QueueType.Outbound)

    return inbound_queue if inbound else None, outbound_queue if outbound else None


def mock_queue_dict_when_received(tenant_id: str = "mock-tenant-id", queue_type: QueueType = QueueType.Inbound):
    queue = mock_queue(tenant_id=tenant_id, queue_type=queue_type)
    return {
        "Queue": {
            "tenant_id": queue.tenant_id,
            "queue_type": queue.queue_type.name,
        }
    }
