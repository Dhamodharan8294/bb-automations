from dataclasses import dataclass

from aws_lambda_powertools.utilities.typing import LambdaContext


# From https://awslabs.github.io/aws-lambda-powertools-python/2.7.1/core/logger/#testing-your-code
@dataclass
class MockLambdaContext(LambdaContext):
    function_name: str = 'test'
    memory_limit_in_mb: int = 128
    invoked_function_arn: str = 'arn:aws:lambda:eu-west-1:809313241:function:test'
    aws_request_id: str = '52fdfc07-2182-154f-163f-5f0f9a621d72'
