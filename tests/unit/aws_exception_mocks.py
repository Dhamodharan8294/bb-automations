from botocore.exceptions import ClientError


def sqs_name_exists():
    return ClientError(operation_name="create_queue",
                       error_response={
                           'Error': {
                               'Code': 'SQS.Client.exceptions.QueueNameExists',
                               'Message': 'Queue name already exists'
                           }
                       })


def sqs_queue_deleted_recently():
    return ClientError(operation_name="create_queue",
                       error_response={
                           'Error': {
                               'Code': 'SQS.Client.exceptions.QueueDeletedRecently',
                               'Message': 'Queue has been deleted recently. Unable to create.'
                           }
                       })


def dynamodb_internal_server_error():
    return ClientError(operation_name="create_table",
                       error_response={
                           'Error': {
                               'Code': 'DynamoDB.Client.exceptions.InternalServerError',
                               'Message': 'Internal error while creating database'
                           }
                       })
