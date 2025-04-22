from dataclasses import dataclass

from aws_cdk import CfnOutput
from aws_cdk.aws_dynamodb import Attribute, AttributeType, TableEncryption
from bb_fnds.cdk_constructs import pipeline_forge
from bb_fnds.cdk_constructs.dynamodb import Table


@dataclass(init=False)
class Dynamodb:
    tenant_resources_table: Table

    def __init__(self, stack: pipeline_forge.Stack):
        self.tenant_resources_table = Table(
            stack,
            'TenantResourcesTable',
            partition_key=Attribute(name='pk', type=AttributeType.STRING),
            sort_key=Attribute(name='sk', type=AttributeType.STRING),
            encryption=TableEncryption.AWS_MANAGED,
        )

        CfnOutput(stack,
                  'TableName',
                  value=self.tenant_resources_table.table_name,
                  description='The name of the DynamoDB table used by this service')
