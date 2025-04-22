from contextlib import contextmanager

from bb_ent_data_services_shared.lambdas.logger import logger

DEFAULT_LOGGER_NAME = 'service_undefined'


@contextmanager
def log_level_override(level: int):
    current_level = logger.getEffectiveLevel()  # type: ignore[attr-defined]
    logger.setLevel(level)

    # run the test
    yield

    logger.setLevel(current_level)
