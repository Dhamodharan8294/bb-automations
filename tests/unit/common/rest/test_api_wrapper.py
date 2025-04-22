import json
import logging

from aws_lambda_powertools.utilities.typing import LambdaContext

from common.rest import BadRequest, RestApiWrapper
from tests.common.core.mock_lambda_context import MockLambdaContext
from tests.common.test_logger import DEFAULT_LOGGER_NAME, log_level_override
from tests.unit.aws_mocks import apigw_event

HANDLER_INFO_LOG = (DEFAULT_LOGGER_NAME, logging.INFO, "my.handler in with pathParameters={'tenantId': 'tenant123'}")


def test_api_wrapper_success(caplog):
    @RestApiWrapper('my.handler')
    def lambda_handler(_event: dict, _context: LambdaContext):
        return {
            'statusCode': 200
        }

    with log_level_override(logging.INFO):
        response = lambda_handler(apigw_event(), MockLambdaContext())

    assert response == {
        'statusCode': 200
    }
    assert caplog.record_tuples == [HANDLER_INFO_LOG]


def test_api_wrapper_debug_logging(caplog):
    @RestApiWrapper('my.handler')
    def lambda_handler(_event: dict, _context: LambdaContext):
        return {
            'statusCode': 200
        }

    lambda_event = apigw_event()

    with log_level_override(logging.DEBUG):
        response = lambda_handler(lambda_event, MockLambdaContext())

    assert response == {
        'statusCode': 200
    }
    assert caplog.record_tuples == [(DEFAULT_LOGGER_NAME, logging.DEBUG, f'my.handler in with {lambda_event}')]


def test_api_wrapper_badrequest_error(caplog):
    @RestApiWrapper('my.handler')
    def lambda_handler(_event: dict, _context: LambdaContext):
        raise BadRequest('myMessage', 'my details')

    with log_level_override(logging.INFO):
        response = lambda_handler(apigw_event(), MockLambdaContext())

    assert response == {
        'statusCode': 400,
        'body': json.dumps({
            'code': 400,
            'message': 'myMessage',
            'details': 'my details',
        }),
    }
    assert caplog.record_tuples == [
        HANDLER_INFO_LOG,
        (DEFAULT_LOGGER_NAME, logging.INFO, 'Returning HTTP 400: myMessage'),
    ]


def test_api_wrapper_unknown_error(caplog):
    @RestApiWrapper('my.handler')
    def lambda_handler(_event: dict, _context: LambdaContext):
        raise ArithmeticError('math is hard')

    with log_level_override(logging.INFO):
        response = lambda_handler(apigw_event(), MockLambdaContext())

    assert response == {
        'statusCode': 500,
        'body': json.dumps({
            'message': 'math is hard'
        }),
    }
    assert caplog.record_tuples == [
        HANDLER_INFO_LOG,
        (DEFAULT_LOGGER_NAME, logging.ERROR, 'Unexpected exception'),
    ]
