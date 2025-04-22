import json
import os
from typing import Sequence

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from bb_ent_data_services_shared.lambdas.logger import logger

xray_tracer = Tracer()

parent_stack_name = os.environ['STACK_NAME']
stack_version = os.environ['STACK_VERSION']
stack_tags = json.loads(os.environ['STACK_TAGS'])
manage_metadata_arn = os.environ['MANAGE_METADATA_ARN']
inbound_dlq_arn = os.environ['INBOUND_DLQ_ARN']
pager_duty_alarm_warning_topic = os.environ.get('PAGER_DUTY_ALARM_WARNING_TOPIC', "")

cloudformation = boto3.resource('cloudformation')

with open('template.yaml', 'r', encoding='ascii') as file:
    template = file.read()


@xray_tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: dict, _context: LambdaContext):
    logger.debug('In with: %s', event)

    tenant_id = event['tenantId']
    client_id = event['clientId']
    is_update = 'isUpdate' in event

    assert tenant_id, 'missing tenantId'
    assert client_id, 'missing clientId'

    stack_name = f'{parent_stack_name}-{tenant_id}'

    tags = {
        **stack_tags,
        'TenantId': tenant_id,
        'ClientId': client_id,
    }
    aws_tags: Sequence = [{
        'Key': k,
        'Value': v
    } for k, v in tags.items()]

    parameters = {
        'TenantId': tenant_id,
        'ClientId': client_id,
        'StackVersion': stack_version,
        'ManageMetadataFunctionArn': manage_metadata_arn,
        'InboundDlqArn': inbound_dlq_arn,
        'PagerDutyAlarmWarningTopic': pager_duty_alarm_warning_topic
    }
    aws_params: Sequence = [{
        'ParameterKey': k,
        'ParameterValue': v,
    } for k, v in parameters.items()]

    if is_update:
        stack = cloudformation.Stack(stack_name)

        logger.info('Updating existing stack %s', stack_name)
        stack.update(TemplateBody=template, Tags=aws_tags, Parameters=aws_params)

    else:
        logger.info('Creating stack %s', stack_name)
        stack = cloudformation.create_stack(
            StackName=stack_name,
            TemplateBody=template,
            Tags=aws_tags,
            Parameters=aws_params,
            # If creation fails, nuke the stack so we can retry later
            OnFailure='DELETE')

    return {
        'stackName': stack_name,
        'stackId': stack.stack_id,
    }
