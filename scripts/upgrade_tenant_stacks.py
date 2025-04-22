#!/usr/bin/env python
"""
This script looks for tenants running old versions of the stack template and upgrades them.
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from time import sleep

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

MAX_EXECUTIONS = 30

parser = argparse.ArgumentParser()
parser.add_argument("--parent-stack", dest="parent_stack", help="The stack to analyze")
parser.add_argument("--limit",
                    dest="limit",
                    type=int,
                    default=MAX_EXECUTIONS,
                    help="The maximum number of upgrades that can be running at once")
parser.add_argument("--commit",
                    dest="commit",
                    action="store_true",
                    default=False,
                    help="If set, changes will be applied; otherwise we will only log")
args = parser.parse_args()

if args.commit and args.limit > MAX_EXECUTIONS:
    print(f"--limit can't exceed {MAX_EXECUTIONS}, or we will trigger AWS rate limiting")
    sys.exit(1)

sfn_client = boto3.client("stepfunctions")
cloudwatch_client = boto3.client("cloudwatch")


def get_resource_names():
    cloudformation = boto3.resource("cloudformation")
    stack = cloudformation.Stack(args.parent_stack)
    stack_resources = stack.resource_summaries.all()

    table_resource = next(r for r in stack_resources if r.resource_type == "AWS::DynamoDB::Table")
    table_name = table_resource.physical_resource_id

    step_function_resource = next(
        r for r in stack_resources
        if r.resource_type == "AWS::StepFunctions::StateMachine" and "UpdateResources" in r.logical_id)
    step_function = step_function_resource.physical_resource_id

    return table_name, step_function


def get_current_version():
    script_dir = os.path.dirname(__file__)
    with open(f"{script_dir}/../functions/tenant_resources/deploy_stack/version.txt", "r", encoding='ascii') as file:
        return file.readline().rstrip("\n")


def upgrade_tenant(index: int, old_version: str, upgrade_step_function_arn: str, tenant_id: str):
    print(f"{index}. Upgrading tenant {tenant_id} from {old_version}", flush=True)
    execution_arn = trigger_upgrade(upgrade_step_function_arn, tenant_id)

    while True:
        sleep(15)
        if step_function_running(execution_arn):
            print(f"{index}. Waiting at {datetime.now()}")
        else:
            print(f"{index}. Complete")
            return


def trigger_upgrade(upgrade_step_function_arn, tenant_id) -> str:
    result = sfn_client.start_execution(
        stateMachineArn=upgrade_step_function_arn,
        input=json.dumps({"tenantId": tenant_id}),
    )
    return result['executionArn']


def step_function_running(execution_arn: str) -> bool:
    result = sfn_client.describe_execution(executionArn=execution_arn)
    status = result["status"]
    if status == "RUNNING":
        return True
    if status == "SUCCEEDED":
        return False
    raise Exception(f"Unexpected status {status} for execution {execution_arn}")


def upgrade_in_progress(table, current_version, tenant_id) -> bool:
    response = table.get_item(Key={
        "pk": f"TENANT_ID#{tenant_id}",
        "sk": f"AUDIT#UPDATE#{current_version}"
    })

    if "Item" not in response:
        return False

    item = response["Item"]
    return item['Status'] in {'Started', 'Success'}


def legacy_outbound_queue_active(tenant_id: str) -> bool:
    """
    Tenant stack version: 0.3.0

    We don't want to remove the outbound queues if they are still active. This looks for any recent events flowing
    through the legacy outbound queue.
    """
    queue_name = f'{args.parent_stack}-{tenant_id}-outbound'
    statistics = cloudwatch_client.get_metric_statistics(Namespace='AWS/SQS',
                                                         MetricName='NumberOfMessagesSent',
                                                         Dimensions=[{
                                                             'Name': 'QueueName',
                                                             'Value': queue_name,
                                                         }],
                                                         StartTime=datetime.now() - timedelta(days=1),
                                                         EndTime=datetime.now(),
                                                         Period=3600,
                                                         Statistics=['Sum'])
    if not statistics:
        raise Exception(f'No stats for {queue_name}')

    non_zero_datapoints = [dp for dp in statistics['Datapoints'] if dp['Sum'] > 0]
    return len(non_zero_datapoints) > 0


def scan_table(table_name, upgrade_step_function, current_version):
    serializer = TypeSerializer()
    deserializer = TypeDeserializer()

    paginator = boto3.client("dynamodb").get_paginator("scan")
    page_iterator = paginator.paginate(
        TableName=table_name,
        FilterExpression="sk = :sk and Version <> :version",
        ExpressionAttributeValues={
            ":sk": serializer.serialize("METADATA"),
            ":version": serializer.serialize(current_version),
        },
    )

    table = boto3.resource("dynamodb").Table(table_name)

    with ThreadPoolExecutor(max_workers=args.limit) as executor:
        need_upgrade = 0

        for page in page_iterator:
            items = page["Items"]
            for item in items:
                tenant_id: str = deserializer.deserialize(item["pk"]).replace("TENANT_ID#", "")
                version: str = deserializer.deserialize(item["Version"])
                if (version.startswith('0.1') or version.startswith('0.2')) and legacy_outbound_queue_active(tenant_id):
                    print(f'Skipping tenant {tenant_id} with active legacy outbound queue')
                    continue

                need_upgrade += 1

                if upgrade_in_progress(table, current_version, tenant_id):
                    # Upgrade is already in progress; count this towards our limit
                    print(f"Tenant {tenant_id} is already upgrading from {version}")
                elif args.commit:
                    executor.submit(upgrade_tenant, need_upgrade, version, upgrade_step_function, tenant_id)
                else:
                    print(f"Tenant {tenant_id} needs upgrading from {version}")

        if args.commit and need_upgrade:
            print(f"{need_upgrade} upgrades scheduled, waiting for futures at {datetime.now()}")

    return need_upgrade > 0


def main():
    table_name, upgrade_step_function = get_resource_names()
    current_version = get_current_version()

    changes_required = scan_table(table_name, upgrade_step_function, current_version)

    print("")
    if changes_required:
        if args.commit:
            print("Upgrades complete.")
        else:
            print("Dry run complete. Re-run with --commit to apply changes.")
    else:
        print("No changes needed.")


if __name__ == "__main__":
    main()
