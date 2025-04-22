import os
from datetime import datetime
from http import HTTPStatus
from typing import Any, Optional

import boto3
import requests
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger
from boto3 import session
from pyfnds.service_discovery import discover_api_url
from requests_aws_sign import AWSV4Sign

from common.data.queues import QueueType, StepFunctionAction, create_queues, get_queue, get_shared_outbound_queue, \
    get_sqs_credentials, get_status_and_retry_information
from common.dates import format_iso8601_date, time_minute_difference
from common.rest import NotFound, RestApiWrapper, rest_response
from common.rest.constants import GET_QUEUE_MAX_RETRIES, GET_QUEUE_RETRY_FACTOR
from common.rest.exceptions import BadRequest

xray_tracer = Tracer()

TENANT_PROVISIONER_ARN = os.environ['TENANT_PROVISIONER_ARN']
ASSUMABLE_ROLE = os.environ['ASSUMABLE_SQS_ROLE']
TABLE_NAME = os.environ['TABLE_NAME']
REGION = os.environ['AWS_REGION']
ALLOW_NON_SAAS_TENANTS = os.getenv('ALLOW_NON_SAAS_TENANTS') == '1'
SKIP_TENANT_API_ERRORS = os.getenv('SKIP_TENANT_API_ERRORS') == '1'
OUTBOUND_QUEUE_ARN = os.environ['OUTBOUND_QUEUE_ARN']
OUTBOUND_QUEUE_URL = os.environ['OUTBOUND_QUEUE_URL']

TENANT_API_URL = discover_api_url(os.environ['TENANT_DISCOVERY_HOST'])
logger.info("Using Tenant API URL: %s", TENANT_API_URL)

sfn_client = boto3.client('stepfunctions')
sts_client = boto3.client('sts')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(TABLE_NAME)


def get_tenant(tenant_id: str) -> dict[str, Any]:
    auth = AWSV4Sign(session.Session(region_name=REGION).get_credentials(), REGION, 'execute-api')
    resp = requests.get(f'{TENANT_API_URL}/tenancy/internal/api/v1/tenants/{tenant_id}', auth=auth, timeout=10)
    if resp.status_code == 200:
        return resp.json()

    if resp.status_code == 404:
        message = f'Tenant ID {tenant_id} not found in tenant service. Tenant API reason message: {resp.reason}'
        if SKIP_TENANT_API_ERRORS:
            logger.error(message)
            return {}
        raise NotFound(message)

    raise RuntimeError(f'Failed to load tenant {tenant_id} from tenant service. '
                       f'Tenant API status code: {resp.status_code:d}, Reason: {resp.reason}')


def _get_saas_client_id(tenant_id: str) -> Optional[str]:
    """
    Confirms that this tenant is allowed to create a connector queue.

    Currently only SaaS Learn instances may create queues, as we don't want to give SH or MH Learn customers direct
    access to the Foundations event bus.

    Note: There is no test coverage for this code yet. REST tests are a no-go because we run these tests with fake
    tenants and have ALLOW_NON_SAAS_TENANTS set to true. Unit tests are awkward because os.environ is initialize once
    during test startup and we can't change the environment after that.
    """
    tenant = get_tenant(tenant_id)
    logger.info('Loaded tenant %s', tenant)

    # Only SaaS instances will have clientId set
    client_id = tenant.get('clientId')

    if not client_id and ALLOW_NON_SAAS_TENANTS:
        # In development (and Dev and Int) we bypass the SaaS Learn requirement so that our local machines can
        # integrate with the connector, and so our REST tests can use generated tenant IDs.
        logger.info('Tenant %s has no client ID, returning generic value', tenant_id)
        return 'Developer'

    return client_id


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@RestApiWrapper('rest_api.get_queue')
def handler(event: dict, _context: LambdaContext):
    parameters = event['pathParameters']
    tenant_id = parameters['tenantId']
    try:
        queue_type = QueueType.from_string(parameters['queueType'])
    except ValueError as error:
        # pylint: disable=raise-missing-from
        raise BadRequest('Failed to parse queueType', str(error))

    queue = get_queue(table, tenant_id=tenant_id, queue_type=queue_type)
    if queue_type == QueueType.Inbound:
        legacy_queue = None
    else:
        legacy_queue = queue
        queue = get_shared_outbound_queue(tenant_id=tenant_id,
                                          outbound_queue_arn=OUTBOUND_QUEUE_ARN,
                                          outbound_queue_url=OUTBOUND_QUEUE_URL)

    if queue is None:
        logger.info('Queue not found for %s', tenant_id)

        client_id = _get_saas_client_id(tenant_id)
        if not client_id:
            # TODO LRN-172116: Rework the mechanism we use to validate sites are SaaS Learn
            # raise Forbidden('Only Learn SaaS tenants may create queues')
            client_id = "Missing"
        logger.info("The ClientId associated with this tenant is %s", client_id)

        audit_info = get_status_and_retry_information(table, tenant_id=tenant_id, action=StepFunctionAction.CREATE)
        if audit_info.status is None:
            create_queues(sfn_client, TENANT_PROVISIONER_ARN, tenant_id, client_id)
            logger.info('Scheduled queue creation for %s', tenant_id)
            return rest_response(HTTPStatus.ACCEPTED)

        if audit_info.status == "Started":
            logger.info("Queue creation already scheduled")
            return rest_response(HTTPStatus.ACCEPTED)

        if audit_info.status == "Failure":
            if audit_info.retry_count == GET_QUEUE_MAX_RETRIES:
                raise Exception("Tenant's Queue Creation has Failed")

            # Retry if it has been requested after a certain amount of time given by Retry_Factor * 2^n
            minutes_until_next_attempt = GET_QUEUE_RETRY_FACTOR * 2**audit_info.retry_count
            if time_minute_difference(datetime.now(), audit_info.updated) < minutes_until_next_attempt:
                logger.info("Scheduled creation failed; %d minutes until retry", minutes_until_next_attempt)
                return rest_response(HTTPStatus.ACCEPTED)

            create_queues(sfn_client, TENANT_PROVISIONER_ARN, tenant_id, client_id, retry_count=audit_info.retry_count)
            logger.info('Scheduled queue creation for %s. Re-attempt %s', tenant_id, audit_info.retry_count)
            return rest_response(HTTPStatus.ACCEPTED)

        delete_info = get_status_and_retry_information(table, tenant_id=tenant_id, action=StepFunctionAction.DELETE)
        if delete_info.status:
            raise NotFound("Tenant's queues have been deleted")

        # This is likely to require manual intervention
        logger.error('Unexpected audit row status %s for tenant %s', audit_info.status, tenant_id)
        raise Exception("Unexpected tenant status")

    credentials = get_sqs_credentials(sts_client, ASSUMABLE_ROLE, queue, legacy_queue=legacy_queue)
    return rest_response(HTTPStatus.OK, to_json(queue, credentials))


def to_json(queue, credentials):
    return {
        'tenantId': queue.tenant_id,
        'type': queue.queue_type.name,
        'arn': queue.sqs_arn,
        'url': queue.url,
        'region': REGION,
        'credentials': {
            'accessKeyId': credentials.access_key_id,
            'secretAccessKey': credentials.secret_access_key,
            'sessionToken': credentials.session_token,
            'expires': format_iso8601_date(credentials.expires),
        }
    }
