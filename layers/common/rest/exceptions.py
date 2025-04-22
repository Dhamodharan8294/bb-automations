from http import HTTPStatus
from typing import Optional


class RestException(Exception):
    """
    A generic exception type that will be caught by RestApiErrorHandler and
    converted to a user-facing error message.

    This should not be thrown directly; one of the subclasses below should be
    used.
    """
    def __init__(self, http_status: int, message: str, details: Optional[str]) -> None:
        super().__init__(details)
        self.http_status = http_status
        self.message = message
        self.details = details

    def to_api_error(self):
        """
        Converts error into something more useful for clients.
        """
        api_error = {
            'code': self.http_status,
            'message': self.message,
        }
        if self.details:
            api_error['details'] = self.details
        return api_error


class BadRequest(RestException):
    """
    Thrown when there is a problem with the data provided by the client.
    """
    def __init__(self, message: str, details: Optional[str] = None) -> None:
        super().__init__(HTTPStatus.BAD_REQUEST, message, details)


class Forbidden(RestException):
    """
    Thrown when the client is attempting an operation they are not allowed to perform.
    """
    def __init__(self, message: str, details: Optional[str] = None) -> None:
        super().__init__(HTTPStatus.FORBIDDEN, message, details)


class NotFound(RestException):
    """
    Thrown when the requested object doesn't exist.
    """
    def __init__(self, message: str, details: Optional[str] = None) -> None:
        super().__init__(HTTPStatus.NOT_FOUND, message, details)
