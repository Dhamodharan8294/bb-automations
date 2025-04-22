import logging

from _pytest.logging import LogCaptureFixture


def assert_no_error_logs(caplog: LogCaptureFixture):
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    print_logging_records(errors)

    assert len(errors) == 0


def assert_contains_error_logs(caplog: LogCaptureFixture):
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    print_logging_records(errors)
    assert len(errors) > 0


def print_logging_records(errors):
    # Print out error information to help with debugging
    for error in errors:
        print(error.getMessage())
        if error.exc_text:
            print(error.exc_text)
