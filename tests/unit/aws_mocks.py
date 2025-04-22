from contextlib import contextmanager
from unittest.mock import patch

from moto.events.models import EventsBackend


@contextmanager
def capture_put_events():
    """
    Captures events sent to EventBridge using the put_events method.

    Ideally moto would do this for us, but right now all they do is swallow the
    input parameter and return an empty array.

    For more info, see put_events in EventsBackend:
    https://github.com/spulec/moto/blob/master/moto/events/models.py#L338,

    For this to work, your test must be annotated with @mock_events.
    """

    put_events_calls = []

    def mock_put_events(events):
        put_events_calls.append(events)
        return []

    with patch.object(EventsBackend, 'put_events', side_effect=mock_put_events):
        yield put_events_calls


def apigw_event(tenant_id='tenant123', queue_type=None):
    """
    Generates an API Gateway event.

    Note that this event cuts a number of corners, and builds just enough for
    what our Lambdas actually need.

    :param tenant_id: tenant to include in the request url
    :param queue_type: (optional) queue type to include in the request url
    """

    path_parameters = {
        'tenantId': tenant_id
    }
    if queue_type:
        path_parameters['queueType'] = queue_type

    event = {
        'resource': '/api/v1/foundationsConnector/test',
        'path': '/api/v1/foundationsConnector/test',
        'httpMethod': 'GET',
        'headers': {
            'accept': '*/*',
            'Host': 'fc9vjt99l7.execute-api.us-east-1.amazonaws.com',
            'User-Agent': 'curl/7.64.1',
            'X-Amzn-Trace-Id': 'Root=1-5ef15d43-0ac4df32dfbb5328d00744c7',
            'X-Forwarded-For': '70.79.250.242',
            'X-Forwarded-Port': '443',
            'X-Forwarded-Proto': 'https'
        },
        'multiValueHeaders': {
            'accept': ['*/*'],
            'Host': ['fc9vjt99l7.execute-api.us-east-1.amazonaws.com'],
            'User-Agent': ['curl/7.64.1'],
            'X-Amzn-Trace-Id': ['Root=1-5ef15d43-0ac4df32dfbb5328d00744c7'],
            'X-Forwarded-For': ['70.79.250.242'],
            'X-Forwarded-Port': ['443'],
            'X-Forwarded-Proto': ['https']
        },
        'queryStringParameters': None,
        'multiValueQueryStringParameters': None,
        'pathParameters': path_parameters,
        'stageVariables': None,
        'requestContext': {
            'resourceId': 'ri4zjv',
            'resourcePath': '/api/v1/foundationsConnector/test',
            'httpMethod': 'GET',
            'extendedRequestId': 'OjuCoHh4oAMFuEg=',
            'requestTime': '23/Jun/2020:01:39:15 +0000',
            'path': '/live/api/v1/foundationsConnector/test',
            'accountId': '257597320193',
            'protocol': 'HTTP/1.1',
            'stage': 'live',
            'domainPrefix': 'fc9vjt99l7',
            'requestTimeEpoch': 1592876355968,
            'requestId': '6569de8b-a8b3-4434-98bd-fb5185f3eef2',
            'identity': {
                'cognitoIdentityPoolId': None,
                'accountId': None,
                'cognitoIdentityId': None,
                'caller': None,
                'sourceIp': '70.79.250.242',
                'principalOrgId': None,
                'accessKey': None,
                'cognitoAuthenticationType': None,
                'cognitoAuthenticationProvider': None,
                'userArn': None,
                'userAgent': 'curl/7.64.1',
                'user': None
            },
            'domainName': 'fc9vjt99l7.execute-api.us-east-1.amazonaws.com',
            'apiId': 'fc9vjt99l7'
        },
        'body': None,
        'isBase64Encoded': False
    }
    return event
