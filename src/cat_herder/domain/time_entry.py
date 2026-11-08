from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from cat_herder.domain.ticket import Sprint

SECONDS_PER_HOUR = 3600
# Hours closer than this are equal, so rounding never makes a difference.
HOURS_TOLERANCE = 0.01


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


@dataclass(frozen=True, kw_only=True)
class Hours:
    """Hours on tickets, and the rest (entries with no ticket)."""

    tickets: float = 0
    others: float = 0

    @classmethod
    def of(cls, entries: Iterable[TimeEntry]) -> 'Hours':
        tickets = others = 0.0
        for entry in entries:
            if entry.ticket_key:
                tickets += entry.hours
            else:
                others += entry.hours
        return cls(tickets=tickets, others=others)

    @classmethod
    def of_nullable(cls, entries: Iterable[TimeEntry] | None) -> 'Hours | None':
        return None if entries is None else cls.of(entries)

    def __add__(self, other: 'Hours') -> 'Hours':
        return Hours(tickets=self.tickets + other.tickets, others=self.others + other.others)

    @property
    def total(self) -> float:
        return self.tickets + self.others

    @property
    def tickets_percent(self) -> float | None:
        """Percent of the hours on tickets. None without hours."""
        return 100 * self.tickets / self.total if self.total else None

    @property
    def others_percent(self) -> float | None:
        """Percent of the hours on tasks without a ticket. None without hours."""
        return 100 * self.others / self.total if self.total else None
