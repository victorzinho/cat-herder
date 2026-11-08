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
