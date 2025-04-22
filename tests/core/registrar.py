#!/usr/bin/env python
"""
Library to get an access token from Registrar. This token may be used when making calls through API Gateway.
This file may be executed directly if you need a token for curl testing.
"""
import json
import sys
from functools import lru_cache

import jwt
import requests
from bb_ent_data_services_shared.core.util import env_var_as_bool
from pyfnds.pytest import Token


class Authorizer(requests.auth.AuthBase):
    def __call__(self, r):
        token = get_jwt_access_token()
        r.headers['Authorization'] = f'Bearer {token}'
        return r


@lru_cache(maxsize=1)
def get_jwt_access_token():
    token = Token(stage='dev', region='us-east-1', is_il4=env_var_as_bool('IS_IL4', default_value=False))
    return token.get_m2m_token()


def main():
    access_token = get_jwt_access_token()

    # Print to stderr - viewable on running script
    decoded_token = json.dumps(jwt.decode(access_token, options={
        "verify_signature": False
    }), indent=2)
    print(f'Registrar token generated:\n{decoded_token}\n', file=sys.stderr)

    print('Sample curl call:', file=sys.stderr)
    print(f"curl -H 'Authorization: Bearer {access_token}' http://api-gateway/endpoint | jq", file=sys.stderr)

    # Header contents assignable to a variable
    print(f'Authorization: Bearer {access_token}')


if __name__ == "__main__":
    main()
