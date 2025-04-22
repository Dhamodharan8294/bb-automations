""" Functions for sending events to eventbridge and handling failures """

from dataclasses import dataclass


@dataclass
class EventBridgeFailure:
    error_code: str
    error_message: str
    event: dict


def send_events_to_eventbridge(eb_client, events: list[dict]) -> list[EventBridgeFailure]:
    """ Send events to an eventbridge """
    response = eb_client.put_events(Entries=events)
    if response['FailedEntryCount'] > 0:
        return _handle_eventbridge_failures(events, response['Entries'])
    return []


def _handle_eventbridge_failures(events: list[dict], response: list[dict]) -> list[EventBridgeFailure]:
    return [
        EventBridgeFailure(
            error_code=r['ErrorCode'],
            error_message=r['ErrorMessage'],
            event=e,
        ) for e, r in zip(events, response) if 'ErrorCode' in r
    ]
