from typing import Optional

from aws_cdk import RemovalPolicy
from aws_cdk import aws_kms as kms
from aws_cdk.aws_iam import AnyPrincipal, PolicyStatement
from bb_fnds.cdk_constructs import pipeline_forge

from cdk.stack_inputs import StackInputs


class Eventbridge:
    eventbridge_sqs_kms_key: Optional[kms.IKey] = None

    def __init__(self, stack: pipeline_forge.Stack, stack_inputs: StackInputs):
        self.stack = stack
        self.stack_inputs = stack_inputs

        self._create_eventbridge_sqs_kms_key()

    def _create_eventbridge_sqs_kms_key(self):
        if self.stack.is_il4:
            # IL4 environments have a single customer-owned key for all encryption
            return

        # Custom encryption key shared by EventBridge and SQS.
        # This is required because EventBridge may not use the AWS-managed SQS encryption key.
        key = kms.Key(self.stack,
                      'EventbridgeSqsKmsKey',
                      alias=f'alias/{self.stack.stack_name}-event-sqs',
                      description=f'Key used by {self.stack.stack_name} for encryption-at-rest of SQS event queues.',
                      enable_key_rotation=True)
        self.eventbridge_sqs_kms_key = key

        # Allow administration of the key
        key.add_to_resource_policy(
            PolicyStatement(
                principals=[AnyPrincipal()],
                actions=[
                    'kms:Create*',
                    'kms:Describe*',
                    'kms:Enable*',
                    'kms:List*',
                    'kms:Put*',
                    'kms:Update*',
                    'kms:Revoke*',
                    'kms:Disable*',
                    'kms:Get*',
                    'kms:Delete*',
                    'kms:ScheduleKeyDeletion',
                    'kms:CancelKeyDeletion',
                ],
                resources=['*'],
                conditions={
                    'StringEquals': {
                        # This grants permission to anything running in the same account, but isn't a concern
                        # since all of our services have boundary policies that restrict their blast radius.
                        'kms:CallerAccount': self.stack.account,
                    }
                }))

        # Allow any authorized SQS consumer to decrypt
        key.add_to_resource_policy(
            PolicyStatement(principals=[AnyPrincipal()],
                            actions=['kms:Decrypt'],
                            resources=['*'],
                            conditions={
                                'StringEquals': {
                                    'kms:CallerAccount': self.stack.account,
                                    'kms:ViaService': f'sqs.{self.stack.region}.amazonaws.com',
                                }
                            }))

        if self.stack_inputs.developer_instance:
            key.apply_removal_policy(RemovalPolicy.DESTROY)
