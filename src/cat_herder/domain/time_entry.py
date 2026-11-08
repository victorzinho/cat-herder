from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from cat_herder.domain.ticket import Sprint

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

    def counts_in_sprint(self, sprint: Sprint, sprint_ticket_keys: Collection[str]) -> bool:
        """Whether its hours count in the sprint.

        An entry naming a sprint counts only in that one. One naming none counts within the sprint's dates if it's on
        one of the sprint's tickets, or on no ticket while the sprint has some in the entry's project.

        Args:
            sprint: the sprint to count it in.
            sprint_ticket_keys: ticket keys in the given sprint.
        """
        if self.sprint:
            return self.sprint == sprint.name
        if self.ticket_key:
            return self.ticket_key in sprint_ticket_keys and sprint.covers(self.start)
        return bool(sprint_ticket_keys) and sprint.covers(self.start)
