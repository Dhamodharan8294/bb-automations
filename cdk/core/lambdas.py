import constructs
from bb_ent_data_services_shared.cdk.constructs.sqs import Queue

from cdk.core.alarms import Alarms
from cdk.core.stack_inputs import SQSAlarmOverrides


class CoreLambdas:
    def __init__(self, alarms: Alarms):
        self.alarms = alarms

    def sqs_queue(self, scope: constructs.Construct, name: str, overrides: SQSAlarmOverrides, **kwargs):
        queue = Queue(scope, name, **kwargs)
        self.alarms.monitor_sqs_queue(queue, overrides)
        return queue
