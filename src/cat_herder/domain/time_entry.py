from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

SECONDS_PER_HOUR = 3600


class TimeEntryFlag(StrEnum):
    """Why the ticket or sprint an entry referred to was dropped."""

    SEVERAL_TICKETS = 'several tickets'
    TICKET_IN_OTHER_PROJECT = 'ticket in another project'
    TICKET_NOT_FOUND = 'ticket not found'
    SPRINT_NOT_FOUND = 'sprint not found'


@dataclass(frozen=True, kw_only=True)
class TimeEntry:
    """Time a person spent, in a space of its source. The person is the source's identity for them.

    ticket_key and sprint are what the entry refers to, and flags say why something it referred to was dropped. Sources
    report them unvalidated, and the time entries service validates them.
    """

    source: str
    id: str
    space: str
    person: str
    description: str
    start: datetime
    end: datetime
    ticket_key: str | None = None
    sprint: str | None = None
    flags: frozenset[TimeEntryFlag] = frozenset()

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / SECONDS_PER_HOUR
