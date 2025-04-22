import logging
from http import HTTPStatus

from bb_ent_data_services_shared.lambdas.logger import logger

from .exceptions import RestException
from .helpers import rest_response


class RestApiWrapper:
    """
    This decorator wraps API Gateway Lambdas, intercepting known e types
    and converting them to strongly typed es. Unknown e types will be
    converted to 500s.
    """
    def __init__(self, endpoint_name):
        self.endpoint_name = endpoint_name

    def __call__(self, func):
        def do_wrap(event, context):
            if logger.isEnabledFor(logging.DEBUG):  # type: ignore[attr-defined]
                logger.debug('%s in with %s', self.endpoint_name, event)
            else:
                parameters = event['pathParameters']
                logger.info('%s in with pathParameters=%s', self.endpoint_name, parameters)

            try:
                return func(event, context)
            except RestException as e:
                logger.info('Returning HTTP %d: %s', e.http_status, e.message)
                return rest_response(e.http_status, e.to_api_error())
            except BaseException as e:  # pylint: disable=broad-except
                logger.exception('Unexpected exception')
                return rest_response(HTTPStatus.INTERNAL_SERVER_ERROR, {
                    'message': str(e)
                })

        return do_wrap
