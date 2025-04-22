#!/usr/bin/env python
"""
This script attempts to fill in holes in our metadata table, adding stub values in cases where older records are
missing a value for a column that was added recently.

Usage:

  # For the Dev stack
  AWS_PROFILE=dsg-sandbox-poweruser \
    scripts/dynamodb_metadata_cleanup.py --parent-stack=fnds-connector-dev

  # For the Int stack
  AWS_PROFILE=dsg-sandbox-poweruser \
    scripts/dynamodb_metadata_cleanup.py --parent-stack=fnds-connector-int

  # For the TP stack
  AWS_PROFILE=dsg-prod-poweruser \
    scripts/dynamodb_metadata_cleanup.py --parent-stack=fnds-connector-tp

  # For the Prod us-east-1 stack (switch to poweruser to commit)
  AWS_PROFILE=dsg-prod-read AWS_REGION=us-east-1 \
    scripts/dynamodb_metadata_cleanup.py --parent-stack=fnds-connector-prod
"""

import argparse

import boto3
from boto3.dynamodb.types import TypeDeserializer

parser = argparse.ArgumentParser()
parser.add_argument("--parent-stack", dest="parent_stack", help="The stack to analyze")
parser.add_argument("--commit",
                    dest="commit",
                    action="store_true",
                    default=False,
                    help="If set, changes will be applied; otherwise we will only audit the existing keys")
args = parser.parse_args()


def get_resource_names():
    cloudformation = boto3.resource("cloudformation")
    stack = cloudformation.Stack(args.parent_stack)
    stack_resources = stack.resource_summaries.all()

    table_resource = next(r for r in stack_resources if r.resource_type == "AWS::DynamoDB::Table")
    table_name = table_resource.physical_resource_id

    return table_name


def scan_table(table_name):
    print(f"Scanning table {table_name}")
    # Raw client for paged queries
    client = boto3.client("dynamodb")
    paginator = client.get_paginator("scan")
    page_iterator = paginator.paginate(TableName=table_name)
    deserializer = TypeDeserializer()

    # Rich client so we can be lazy and avoid manual serialization
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Load information about all tenants
    tenants = {}
    for page in page_iterator:
        for item in page["Items"]:
            tenant_id = deserializer.deserialize(item["pk"])
            sort_key = deserializer.deserialize(item["sk"])

            tenant = tenants.get(tenant_id, {})
            if sort_key == "METADATA":
                tenant["metadata"] = item
            elif sort_key.startswith("AUDIT#CREATE"):
                tenant["create"] = item
            elif sort_key.startswith("AUDIT#DELETE"):
                tenant["delete"] = item
            tenants[tenant_id] = tenant

    changes_required = False

    for tenant_id, tenant in tenants.items():
        metadata = tenant.get("metadata")
        audit_create = tenant.get("create")
        audit_delete = tenant.get("delete")

        metadata_key = {
            "pk": tenant_id,
            "sk": "AUDIT#METADATA",
        }
        audit_create_key = {
            "pk": tenant_id,
            "sk": "AUDIT#CREATE"
        }

        # 2020-12-11: 0.1.17 now requires a ClientId attribute
        if metadata and "ClientId" not in metadata:
            print(f"{tenant_id} is missing its ClientId")
            changes_required = True

            if args.commit:
                print("- Injecting a fake ClientId")
                table.update_item(Key=metadata_key,
                                  UpdateExpression="SET ClientId=:clientId",
                                  ExpressionAttributeValues={":clientId": "Developer"},
                                  ConditionExpression="attribute_not_exists(ClientId)")

        # 2020-12-11: LRN-170519 can potentially create a metadata row that's missing this attribute
        if metadata and "CreatedAt" not in metadata:
            print(f"{tenant_id} is missing its CreatedAt timestamp")
            changes_required = True

            if "UpdatedAt" not in metadata:
                print("- Error: Record doesn't have an UpdatedAt value either; no correction can be made")
            else:
                created_at = deserializer.deserialize(metadata["UpdatedAt"])
                if args.commit:
                    print("- Fixing the CreatedAt timestamp")
                    table.update_item(Key=metadata_key,
                                      UpdateExpression="SET CreatedAt=:createdAt",
                                      ExpressionAttributeValues={":createdAt": created_at},
                                      ConditionExpression="attribute_not_exists(CreatedAt)")

        # 2021-01-26: We hit the 5000 alarm limit in Dev. A number of stacks failed to create, but the step function
        # was incorrectly marked as successful
        if not metadata and audit_create and not audit_delete:
            create_status = deserializer.deserialize(audit_create["Status"])
            if create_status == "Success":
                print(f"{tenant_id} is missing its metadata")
                changes_required = True

                if args.commit:
                    print(f"- Deleting audit#create row for {tenant_id}")
                    table.delete_item(Key=audit_create_key)

        # 2021-02-05: We hit the 5000 alarm limit in Prod. A number of stacks were successful created, but errors
        # checking the status caused the step function to mark the audit record as failed.
        if metadata and audit_create and not audit_delete:
            create_status = deserializer.deserialize(audit_create["Status"])
            if create_status == "Failure":
                print(f"{tenant_id} was successfully created but marked as a failure")
                changes_required = True

                if args.commit:
                    print(f"- Updating audit#create row for {tenant_id}")
                    table.update_item(Key=audit_create_key,
                                      UpdateExpression="SET #status=:status",
                                      ExpressionAttributeNames={"#status": "Status"},
                                      ExpressionAttributeValues={":status": "Success"})

    return changes_required


def main():
    table_name = get_resource_names()

    changes_required = scan_table(table_name)

    print("")
    if changes_required:
        if args.commit:
            print("Changes applied.")
        if not args.commit:
            print("Dry run complete. Re-run with --commit to apply changes.")
    else:
        print("No changes needed.")


if __name__ == "__main__":
    main()
