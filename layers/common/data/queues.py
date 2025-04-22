import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from bb_ent_data_services_shared.lambdas.logger import logger

from common.dates import parse_iso8601_date


class QueueType(Enum):
    Inbound = 1  # pylint: disable=invalid-name
    Outbound = 2  # pylint: disable=invalid-name

    @staticmethod
    def from_string(label: str):
        lc_label = label.lower()
        for queue_type in QueueType:
            if queue_type.name.lower() == lc_label:
                return queue_type
        raise ValueError('Unknown queue_type: ' + label)


class StepFunctionAction(Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

    def __str__(self):
        return str(self.name)


@dataclass
class SqsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expires: datetime


# https://confluence.bbpd.io/display/PLAT/Foundations+Connector+proposal#FoundationsConnectorproposal-DomainDefinition
@dataclass
class Queue:
    tenant_id: str
    queue_type: QueueType
    sqs_arn: str
    url: str
    created_date: Optional[str]
    modified_date: Optional[str]


@dataclass
class AuditInformation:
    status: Optional[str] = None
    updated: datetime = datetime.now()
    retry_count: int = 0


def get_metadata(table, tenant_id: str) -> Optional[dict]:
    query_response = table.get_item(Key={
        'pk': f"TENANT_ID#{tenant_id}",
        'sk': "METADATA",
    })
    return query_response.get('Item')


def get_queue(table, tenant_id: str, queue_type: QueueType) -> Optional[Queue]:
    """ Get per-tenant queue information from database """
    logger.info('DataLayer: Seeking queue for tenant %s and with type %s', tenant_id, queue_type.name)

    metadata = get_metadata(table, tenant_id)
    # No queue was found.
    if metadata is None:
        return None

    # A queue was found. Return the corresponding object
    return item_to_queue(tenant_id, metadata, queue_type)


def get_shared_outbound_queue(tenant_id: str, outbound_queue_arn: str, outbound_queue_url: str) -> Queue:
    # We have a central queue for all events outbound from Learn
    return Queue(tenant_id=tenant_id,
                 queue_type=QueueType.Outbound,
                 sqs_arn=outbound_queue_arn,
                 url=outbound_queue_url,
                 created_date=None,
                 modified_date=None)


def get_queues(table, tenant_id: str) -> list[Queue]:
    """
    Get a list of the queues that are associated with a tenant. Historically there would have been both inbound and
    outbound queues, but modern stacks only have a private inbound queue and share the common outbound queue.
    """
    logger.info('DataLayer: Seeking queues for tenant %s', tenant_id)

    metadata = get_metadata(table, tenant_id)
    # No queue was found.
    if metadata is None:
        return []

    # A queue was found. Return the corresponding object
    return item_to_queues(tenant_id, metadata)


def _get_audit_information(table, tenant_id: str, action: StepFunctionAction, version=None) -> Optional[dict]:
    if action == StepFunctionAction.UPDATE:
        assert version, "Version is required"
    else:
        assert not version, "Version not allowed"

    query_response = table.get_item(Key={
        'pk': f"TENANT_ID#{tenant_id}",
        'sk': f"AUDIT#{action}" if version is None else f"AUDIT#{action}#{version}",
    })
    return query_response.get('Item')


def get_status(table, tenant_id: str, action: StepFunctionAction, version=None) -> Optional[str]:
    if item := _get_audit_information(table, tenant_id, action, version):
        return item['Status']
    return None


def get_status_and_retry_information(table,
                                     tenant_id: str,
                                     action: StepFunctionAction,
                                     version=None) -> AuditInformation:
    if item := _get_audit_information(table, tenant_id, action, version):
        return AuditInformation(status=item["Status"],
                                retry_count=int(item.get("RetryCount", "0")),
                                updated=parse_iso8601_date(item["UpdatedAt"]))
    return AuditInformation()


def create_queues(sfn_client, provision_arn: str, tenant_id: str, client_id: str, retry_count: int = 0):
    """ Create a queue for a given tenant and type """
    sfn_client.start_execution(stateMachineArn=provision_arn,
                               input=json.dumps({
                                   'tenantId': tenant_id,
                                   'currentCount': str(retry_count),
                                   'retryCount': str(retry_count + 1),
                                   "clientId": client_id,
                               }))


def delete_queues(sfn_client, delete_arn, tenant_id: str) -> None:
    """ Delete all queues for a specific tenant """
    sfn_client.start_execution(stateMachineArn=delete_arn, input=json.dumps({
        'tenantId': tenant_id
    }))


def get_sqs_credentials(sts_client, role: str, queue: Queue, legacy_queue: Optional[Queue]) -> SqsCredentials:
    session_name = get_sqs_credential_id(queue.tenant_id, queue.queue_type)
    actions = _get_policy_actions_for_queue(queue)

    resources = [queue.sqs_arn]
    if legacy_queue:
        resources.append(legacy_queue.sqs_arn)

    response = sts_client.assume_role(
        RoleArn=role,
        RoleSessionName=session_name,
        # https://aws.amazon.com/premiumsupport/knowledge-center/iam-role-chaining-limit/
        DurationSeconds=3600,
        Policy=json.dumps({
            'Version': '2012-10-17',
            'Statement': [{
                'Effect': 'Allow',
                'Action': actions,
                'Resource': resources,
            }]
        }),
    )

    return SqsCredentials(
        response['Credentials']['AccessKeyId'],
        response['Credentials']['SecretAccessKey'],
        response['Credentials']['SessionToken'],
        response['Credentials']['Expiration'],
    )


def get_sqs_credential_id(tenant_id: str, queue_type: QueueType):
    return f"{tenant_id}-{queue_type.name.lower()}-{str(uuid.uuid4())[:8]}"


def _get_policy_actions_for_queue(queue: Queue) -> list[str]:
    if queue.queue_type == QueueType.Inbound:
        return [
            'sqs:GetQueueAttributes',
            'sqs:DeleteMessage',
            'sqs:ReceiveMessage',
        ]

    return [
        'sqs:GetQueueAttributes',
        'sqs:SendMessage',
    ]


def item_to_queue(tenant_id: str, queue_dict: dict, queue_type: QueueType) -> Optional[Queue]:
    if queue_type == QueueType.Outbound and 'OutboundQueueArn' not in queue_dict:
        return None

    return Queue(
        tenant_id=tenant_id,
        queue_type=queue_type,
        sqs_arn=queue_dict['InboundQueueArn'] if queue_type == QueueType.Inbound else queue_dict['OutboundQueueArn'],
        url=queue_dict['InboundQueueUrl'] if queue_type == QueueType.Inbound else queue_dict['OutboundQueueUrl'],
        created_date=queue_dict['CreatedAt'],
        modified_date=queue_dict.get('UpdatedAt'))


def item_to_queues(tenant_id, queue_dict) -> list[Queue]:
    result = []
    if inbound_queue := item_to_queue(tenant_id, queue_dict, QueueType.Inbound):
        result.append(inbound_queue)
    if outbound_queue := item_to_queue(tenant_id, queue_dict, QueueType.Outbound):
        result.append(outbound_queue)
    return result
