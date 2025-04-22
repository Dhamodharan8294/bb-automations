from dataclasses import dataclass

from aws_cdk import Duration, Stack
from bb_ent_data_services_shared.cdk.constructs.sqs import Queue

from cdk.core.alarms import Alarms
from cdk.core.stack_inputs import SQSAlarmOverrides


@dataclass(init=False)
class CommonDeadLetterQueues:
    def __init__(self, stack: Stack, alarms: Alarms):
        # Tenant stacks maintain references to these dead letter queues. Do not allow the ID/ARN to change.
        self.inbound_dlq = Queue(
            stack,
            'TenantsInboundDlq',
            queue_name=f'{stack.stack_name}-TenantsInboundDLQ',
            # This timeout is only relevant if the DLQ is being re-processed. In that case, odds are high that SRE is
            # only activating the mapping long enough to retry each event once.
            visibility_timeout=Duration.hours(2),
        )
        self.outbound_dlq = Queue(
            stack,
            'TenantsOutboundDlq',
            queue_name=f'{stack.stack_name}-TenantsOutboundDLQ',
        )

        dlq_overrides = SQSAlarmOverrides()
        dlq_overrides.set_dlq_defaults()
        alarms.monitor_sqs_queue(self.inbound_dlq, dlq_overrides)
        alarms.monitor_sqs_queue(self.outbound_dlq, dlq_overrides)
