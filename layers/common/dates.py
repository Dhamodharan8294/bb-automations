from datetime import datetime, timezone


def format_iso8601_date(date: datetime):
    """
    Formats a datetime object as UTC time (represented by 'Z') with milliseconds

    :param date the datetime to format
    :returns: the formatted string
    """
    return date.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def parse_iso8601_date(iso_timestamp) -> datetime:
    """
    Converts an ISO-8601 date string to a Python datetime
    """
    return datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))


def time_minute_difference(end_date: datetime, start_date: datetime):
    """
    Gets the difference in minutes between two dates.
    """
    if not end_date.tzinfo:
        end_date = end_date.replace(tzinfo=timezone.utc)

    if not start_date.tzinfo:
        start_date = start_date.replace(tzinfo=timezone.utc)

    return (end_date - start_date).total_seconds() / 60
