import re
from collections.abc import Collection
from datetime import datetime

from cat_herder.domain.config import TogglSourceConfig
from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.sources.toggl.client import JsonObject

TICKET_KEY = re.compile(r'\b[A-Z][A-Z0-9]*-\d+\b')


def time_entry(
    config: TogglSourceConfig, row: JsonObject, entry: JsonObject, space: str, ticket_spaces: Collection[str]
) -> TimeEntry:
    """One of a report row's entries, with the key in its description in one of ticket_spaces as its ticket key, or none
    and a flag if it has several.
    """
    description: str = row['description'] or ''
    found = dict.fromkeys(TICKET_KEY.findall(description))
    keys = [key for key in found if key.rpartition('-')[0] in ticket_spaces]
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
