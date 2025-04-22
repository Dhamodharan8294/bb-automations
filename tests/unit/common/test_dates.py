from datetime import datetime, timezone
import pytz

from common.dates import format_iso8601_date, parse_iso8601_date, time_minute_difference


def test_parse_and_format_dates():
    date = datetime(2020, 5, 9, 1, 14, 16, 123000, timezone.utc)
    formatted_date = '2020-05-09T01:14:16.123Z'

    assert format_iso8601_date(date) == formatted_date
    assert parse_iso8601_date(formatted_date) == date


def test_time_minute_difference_utc():
    start_date = datetime(2021, 1, 5, 9, 23, 15, 324080, timezone.utc)
    end_date = datetime(2021, 1, 5, 10, 6, 15, 324080, timezone.utc)

    assert time_minute_difference(end_date, start_date) == 43.0


def test_time_minute_difference_non_utc_start_date():
    pacific = pytz.timezone("US/Pacific")
    start_date = datetime(2021, 1, 4, 9, 23, 15, 324080, pacific)
    end_date = datetime(2021, 1, 5, 10, 6, 15, 324080, timezone.utc)

    assert time_minute_difference(end_date, start_date) == 1010.0


def test_time_minute_difference_non_utc_end_date():
    pacific = pytz.timezone("US/Pacific")
    start_date = datetime(2021, 1, 4, 9, 23, 15, 324080, timezone.utc)
    end_date = datetime(2021, 1, 5, 10, 6, 15, 324080, pacific)

    assert time_minute_difference(end_date, start_date) == 1956.0


def test_time_minute_difference_naive_start_date():
    start_date = datetime(2021, 1, 5, 9, 23, 15, 324080)  # "naive" datetime, i.e. not timezone-aware
    end_date = datetime(2021, 1, 5, 10, 7, 15, 324080, timezone.utc)

    assert time_minute_difference(end_date, start_date) == 44.0


def test_time_minute_difference_naive_end_date():
    start_date = datetime(2021, 1, 5, 9, 23, 15, 324080, timezone.utc)
    end_date = datetime(2021, 1, 5, 10, 7, 15, 324080)  # "naive" datetime, i.e. not timezone-aware

    assert time_minute_difference(end_date, start_date) == 44.0


def test_time_minute_difference_naive_end_date_non_utc_start_date():
    pacific = pytz.timezone("US/Pacific")
    start_date = datetime(2021, 1, 4, 9, 23, 15, 324080, pacific)
    end_date = datetime(2021, 1, 5, 10, 7, 15, 324080)  # "naive" datetime, i.e. not timezone-aware

    assert time_minute_difference(end_date, start_date) == 1011.0
