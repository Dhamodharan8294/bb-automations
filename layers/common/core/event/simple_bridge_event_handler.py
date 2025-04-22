import abc
import json

from bb_ent_data_services_shared.lambdas.logger import logger


class SimpleBridgeEventHandler(abc.ABC):
    """
    Similar to BridgeEventHandler, but without support for logging recurring errors, etc. Handles events from either
    SQS or EventBridge.

    Note that Lambdas using this handler must set report_batch_item_failures=True in their SqsEventSource.
    """
    @abc.abstractmethod
    def handle_event(self, *, event_id: str, source: str, detail_type: str, event_detail: dict) -> None:
        ...

    def lambda_handler(self, event: dict):
        logger.debug('Received event: %s', event)
        if 'Records' in event:
            return self.handle_sqs_event(event)

        return self.handle_eventbridge_event(event)

    def handle_sqs_event(self, event: dict):
        failed_message_ids = []

        for record in event['Records']:
            try:
                body = json.loads(record['body'])
                self.process_event(body)
            except:  # pylint: disable=bare-except
                logger.exception('Failed to process SQS record %s', record)
                failed_message_ids.append(record['messageId'])

        return {
            'batchItemFailures': [{
                'itemIdentifier': message_id
            } for message_id in failed_message_ids]
        }

    def handle_eventbridge_event(self, event: dict) -> None:
        try:
            self.process_event(event)
        except:  # pylint: disable=bare-except
            # Since EventBridge sends us messages one at a time, allow the entire Lambda to fail so that the event
            # can be forwarded to our SQS input queue for extended retries.
            logger.error('Failed to process EventBridge event %s', event)
            raise

    def process_event(self, event: dict) -> None:
        event_id: str = event['id']
        source: str = event['source']
        detail_type: str = event['detail-type']
        detail: dict = event['detail']

        self.handle_event(event_id=event_id, source=source, detail_type=detail_type, event_detail=detail)
