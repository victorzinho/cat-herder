import re
from datetime import datetime

from cat_herder.domain.config import TogglSourceConfig
from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.sources.toggl.client import JsonObject

TICKET_KEY = re.compile(r'\b[A-Z][A-Z0-9]*-\d+\b')


def time_entry(config: TogglSourceConfig, row: JsonObject, entry: JsonObject, space: str) -> TimeEntry:
    """One of a report row's entries, with the ticket key in its description, or none and a flag if it has several."""
    description: str = row['description'] or ''
    keys = list(dict.fromkeys(TICKET_KEY.findall(description)))
    return TimeEntry(
        source=config.slug,
        id=str(entry['id']),
        space=space,
        person=str(row['user_id']),
        description=description,
        start=datetime.fromisoformat(entry['start']),
        end=datetime.fromisoformat(entry['stop']),
        ticket_key=keys[0] if len(keys) == 1 else None,
        flags=frozenset({TimeEntryFlag.SEVERAL_TICKETS}) if len(keys) > 1 else frozenset(),
    )
