from http import HTTPStatus

from common.rest import rest_response


def test_rest_response():
    response = rest_response(HTTPStatus.METHOD_NOT_ALLOWED, {
        'a': 'A',
        'b': 'B',
    })
    assert response == {
        'statusCode': 405,
        'body': '{"a": "A", "b": "B"}'
    }
