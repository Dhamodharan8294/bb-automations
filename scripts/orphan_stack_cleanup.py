#!/usr/bin/env python
"""
This script looks for tenant stacks that have been orphaned because the upstream site no longer exists in Registrar.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from time import sleep

import boto3
from boto3.dynamodb.types import TypeDeserializer

MAX_EXECUTIONS = 25

parser = argparse.ArgumentParser()
parser.add_argument(
    '--environment',
    dest='environment',
    help='The Foundations environment to analyze',
    default='int',
)
parser.add_argument(
    '--commit',
    dest='commit',
    action='store_true',
    default=False,
    help='If set, changes will be applied; otherwise we will only log',
)
args = parser.parse_args()


@dataclass
class FoundationsEnvironment:
    # Profile name from ~/.aws/config with write access to fnds account
    fnds_profile: str
    # Name of fnds-connector parent stack
    parent_stack_name: str
    # ARN of fnds-connector delete step function
    step_function: str
    # Profile name from ~/.aws/config with DynamoDB read access to registrar account
    registrar_profile: str
    # Name of Registrar DynamoDB table
    registrar_dynamo_table: str


@dataclass
class StackInfo:
    name: str
    created: datetime


fnds_envs = {
    'dev': FoundationsEnvironment(
        fnds_profile='foundations-sandbox',
        parent_stack_name='fnds-connector-dev',
        step_function='arn:aws:states:us-east-1:257597320193:stateMachine:fnds-connector-dev-delete',
        registrar_profile='registrar-dev',
        registrar_dynamo_table='fnds-registrar-dev-sites',
    ),
    'int': FoundationsEnvironment(
        fnds_profile='foundations-sandbox',
        parent_stack_name='fnds-connector-int',
        step_function='arn:aws:states:us-east-1:257597320193:stateMachine:fnds-connector-int-delete',
        registrar_profile='registrar-dev',
        registrar_dynamo_table='fnds-registrar-int-sites',
    ),
    'tp': FoundationsEnvironment(
        fnds_profile='foundations-prod',
        parent_stack_name='fnds-connector-tp',
        step_function='arn:aws:states:us-east-1:699697073451:stateMachine:fnds-connector-tp-delete',
        registrar_profile='registrar-prod',
        registrar_dynamo_table='fnds-registrar-tp-sites',
    ),
}
fnds_env = fnds_envs[args.environment]

fnds_session = boto3.session.Session(profile_name=fnds_env.fnds_profile)
cloudformation = fnds_session.client('cloudformation')
sfn_client = fnds_session.client('stepfunctions')

registrar_session = boto3.session.Session(profile_name=fnds_env.registrar_profile)
dynamodb = registrar_session.client('dynamodb')


def main():
    # List our tenant stacks
    stacks_before = list_stacks()

    # Build list of known Registrar tenant IDs
    registrar_tenants = list_registrar_tenants()

    # List our stacks again, in case there has been a change since we started
    stacks_after = list_stacks()

    # Compare stacks with the tenants present in Registrar
    stacks_to_delete = compare_tenants(registrar_tenants, stacks_before, stacks_after)

    if args.commit:
        print('Deleting stacks...')
        delete_stacks(stacks_to_delete)
        print('Done')


def list_stacks() -> dict[str, StackInfo]:
    print('Listing our stacks...')

    valid_statuses = [
        'CREATE_IN_PROGRESS',
        'CREATE_FAILED',
        'CREATE_COMPLETE',
        'ROLLBACK_IN_PROGRESS',
        'ROLLBACK_FAILED',
        'ROLLBACK_COMPLETE',
        'DELETE_FAILED',
        'UPDATE_IN_PROGRESS',
        'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS',
        'UPDATE_COMPLETE',
        'UPDATE_FAILED',
        'UPDATE_ROLLBACK_IN_PROGRESS',
        'UPDATE_ROLLBACK_FAILED',
        'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS',
        'UPDATE_ROLLBACK_COMPLETE',
        'REVIEW_IN_PROGRESS',
        'IMPORT_IN_PROGRESS',
        'IMPORT_COMPLETE',
        'IMPORT_ROLLBACK_IN_PROGRESS',
        'IMPORT_ROLLBACK_FAILED',
        'IMPORT_ROLLBACK_COMPLETE',
    ]

    stacks = {}

    paginator = cloudformation.get_paginator('list_stacks')
    page_iterator = paginator.paginate(StackStatusFilter=valid_statuses)
    for page in page_iterator:
        stack_summaries = page['StackSummaries']
        for summary in stack_summaries:
            stack_name: str = summary['StackName']
            if (stack_name.startswith(fnds_env.parent_stack_name)
                    and len(stack_name) == len(fnds_env.parent_stack_name) + 37):
                created = summary['CreationTime']
                stacks[stack_name] = StackInfo(name=stack_name, created=created)

    return stacks


def list_registrar_tenants() -> set[str]:
    print("Listing Registrar's tenants...")

    paginator = dynamodb.get_paginator('scan')
    page_iterator = paginator.paginate(
        TableName=fnds_env.registrar_dynamo_table,
        AttributesToGet=['tenantId'],
    )
    deserializer = TypeDeserializer()

    tenant_ids = set()
    for page in page_iterator:
        for item in page['Items']:
            if tenant_id := item.get('tenantId'):
                tenant_ids.add(deserializer.deserialize(tenant_id))

    return tenant_ids


def get_tenant_id(stack_name: str) -> str:
    return stack_name.replace(f'{fnds_env.parent_stack_name}-', '')


def build_stack_name(tenant_id: str) -> str:
    return f'{fnds_env.parent_stack_name}-{tenant_id}'


def delete_stacks(stacks: list[StackInfo]):
    with ThreadPoolExecutor(max_workers=MAX_EXECUTIONS) as executor:
        for index, stack in enumerate(stacks):
            executor.submit(delete_stack, index, stack.name)


def delete_stack(index: int, stack_name: str):
    print(f'{index}. Deleting stack {stack_name} at {datetime.now()}', flush=True)

    execution_arn = trigger_delete(stack_name)
    while True:
        sleep(20)
        if step_function_running(execution_arn):
            print(f'{index}. Waiting at {datetime.now()}')
        else:
            print(f'{index}. Complete')
            return


def trigger_delete(stack_name: str) -> str:
    tenant_id = get_tenant_id(stack_name)
    result = sfn_client.start_execution(
        stateMachineArn=fnds_env.step_function,
        input=json.dumps({
            'tenantId': tenant_id
        }),
    )
    return result['executionArn']


def step_function_running(execution_arn: str) -> bool:
    result = sfn_client.describe_execution(executionArn=execution_arn)
    status = result['status']
    if status == 'RUNNING':
        return True
    if status == 'SUCCEEDED':
        return False
    raise Exception(f'Unexpected status {status} for execution {execution_arn}')


def compare_tenants(registrar_tenants: set[str], stacks_before: dict[str, StackInfo],
                    stacks_after: dict[str, StackInfo]) -> list[StackInfo]:
    # Only inspect the stacks that are present both before and after querying Registrar
    stack_tenants_before = {get_tenant_id(stack_name)
                            for stack_name in stacks_before.keys()}
    stack_tenants_after = {get_tenant_id(stack_name)
                           for stack_name in stacks_after.keys()}
    stack_tenants_to_inspect = stack_tenants_before & stack_tenants_after

    # If the tenant ID no longer exists in Registrar, schedule the stack for deletion
    stacks_to_delete = []
    for tenant_id in stack_tenants_to_inspect:
        if tenant_id not in registrar_tenants:
            stack = stacks_before[build_stack_name(tenant_id)]
            stacks_to_delete.append(stack)

    # Display statistics
    #
    # Note: Listing Registrar sites without Foundations stacks is not interesting because many CI sites are integ-test
    # only and do not call fnds-connector to request queues.
    for stack in stacks_to_delete:
        print(f'Foundations stack has no Registrar tenant: {stack.name}, created={stack.created}')

    return stacks_to_delete


if __name__ == '__main__':
    main()
