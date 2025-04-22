import json
from typing import Optional, Any


def rest_response(status_code: int, body: Optional[dict] = None):
    """
    Builds an API Gateway-compatible REST response for a Lambda.
    """

    response: dict[str, Any] = {
        'statusCode': status_code
    }
    if body is not None:
        response['body'] = json.dumps(body)

    return response
