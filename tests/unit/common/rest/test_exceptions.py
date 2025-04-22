from common.rest import BadRequest, NotFound

MESSAGE = 'Error message'
DETAILS = 'Error details'


def test_badrequest_to_api_error():
    error = BadRequest(MESSAGE, DETAILS)
    assert error.to_api_error() == {
        'code': 400,
        'message': MESSAGE,
        'details': DETAILS,
    }


def test_notfound_to_api_error():
    error = NotFound(MESSAGE, DETAILS)
    assert error.to_api_error() == {
        'code': 404,
        'message': MESSAGE,
        'details': DETAILS,
    }


def test_to_api_error_no_details():
    error = NotFound(MESSAGE)
    assert error.to_api_error() == {
        'code': 404,
        'message': MESSAGE,
    }
