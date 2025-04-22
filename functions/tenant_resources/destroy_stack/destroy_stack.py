import os

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger

xray_tracer = Tracer()

parent_stack_name = os.environ['STACK_NAME']

cloudformation = boto3.resource('cloudformation')


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: dict, _context: LambdaContext):
    logger.debug('In with: %s', event)

    tenant_id = event['tenantId']
    assert tenant_id, 'missing tenantId'

    stack_name = f'{parent_stack_name}-{tenant_id}'
    logger.info('Deleting stack %s', stack_name)

    stack = cloudformation.Stack(stack_name)
    stack.delete()

    return {
        'stackName': stack_name
    }
