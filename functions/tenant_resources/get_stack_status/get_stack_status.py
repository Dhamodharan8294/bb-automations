import boto3
import botocore
from aws_lambda_powertools import Tracer

from bb_ent_data_services_shared.lambdas.logger import logger

xray_tracer = Tracer()

cloudformation = boto3.resource('cloudformation')

FAILURE_STATUSES = {
    'CREATE_FAILED',
    'ROLLBACK_FAILED',
    'ROLLBACK_COMPLETE',
    'DELETE_FAILED',
    'UPDATE_ROLLBACK_FAILED',
    'UPDATE_ROLLBACK_COMPLETE',
    'IMPORT_ROLLBACK_FAILED',
    'IMPORT_ROLLBACK_COMPLETE',
}


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event, _context):
    logger.debug('In with: %s', event)

    stack_name = event['stackName']
    assert stack_name, 'missing stackName'

    try:
        stack = cloudformation.Stack(stack_name)
        status = stack.stack_status
        logger.info('Stack status for %s is %s', stack_name, status)
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] != 'ValidationError':
            raise

        logger.info('Stack %s not found', stack_name)
        status = 'DELETE_COMPLETE'

    return {
        'status': status,
        'isComplete': ('IN_PROGRESS' not in status),
        'isFailure': (status in FAILURE_STATUSES),
    }
