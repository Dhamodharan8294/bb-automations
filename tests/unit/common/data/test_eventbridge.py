from common.data.eventbridge import _handle_eventbridge_failures, EventBridgeFailure


def test_handle_eventbridge_failures():
    eventbridge_response = {
        'FailedEntryCount': 2,
        'Entries': [{
            'EventId': '00000000-0000-0000-000000000000'
        }, {
            'ErrorCode': '234',
            'ErrorMessage': 'Error 1'
        }, {
            'ErrorCode': '345',
            'ErrorMessage': 'Error 2'
        }]
    }

    events = [{
        'foo': 'valid'
    }, {
        'bar': 'invalid'
    }, {
        'foobar': 'invalid'
    }]
    response = _handle_eventbridge_failures(events, eventbridge_response['Entries'])
    assert response == [
        EventBridgeFailure(event=events[1],
                           error_code=eventbridge_response['Entries'][1]['ErrorCode'],
                           error_message=eventbridge_response['Entries'][1]['ErrorMessage']),
        EventBridgeFailure(event=events[2],
                           error_code=eventbridge_response['Entries'][2]['ErrorCode'],
                           error_message=eventbridge_response['Entries'][2]['ErrorMessage'])
    ]


# TODO: moto mock when https://github.com/spulec/moto/pull/3145 is released
