from datetime import datetime


def parse(value: str) -> datetime:
    """An aware datetime from an ISO string with its offset, such as 2026-10-01T09:00:00Z.

    Raises:
        ValueError: if the string isn't ISO, or has no offset.
    """
    parsed = datetime.fromisoformat(value)
    if not parsed.tzinfo:
        raise ValueError(f'{value} has no offset')
    return parsed


def august(day: int) -> datetime:
    """That day of August 2026, at 09:00 UTC, as for the other months."""
    return parse(f'2026-08-{day:02}T09:00:00Z')


def september(day: int) -> datetime:
    return parse(f'2026-09-{day:02}T09:00:00Z')


def october(day: int) -> datetime:
    return parse(f'2026-10-{day:02}T09:00:00Z')


def november(day: int) -> datetime:
    return parse(f'2026-11-{day:02}T09:00:00Z')
