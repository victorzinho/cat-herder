import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

type CustomValue = str | float | None

# How a Change to sprints joins the names of the sprints holding the ticket.
_SPRINT_NAMES_SEPARATOR = ', '


class TicketState(StrEnum):
    OPEN = 'open'
    DONE = 'done'
    DISCARDED = 'discarded'


class SprintState(StrEnum):
    NOT_STARTED = 'not started'
    IN_PROGRESS = 'in progress'
    ENDED = 'ended'


@dataclass(frozen=True, kw_only=True)
class Sprint:
    """Identified by source and ID."""

    source: str
    id: str
    name: str
    state: SprintState
    start: datetime | None = None
    planned_end: datetime | None = None
    actual_end: datetime | None = None

    @property
    def duration(self) -> timedelta | None:
        """From its start to its end (actual or planned). None without a start or an end."""
        end = self.actual_end or self.planned_end
        return end - self.start if self.start and end else None

    def covers(self, moment: datetime) -> bool:
        """Whether the moment is between its start and actual end, both included.

        A sprint that hasn't ended runs from its start, and one that hasn't started covers nothing.
        """
        if not self.start or moment < self.start:
            return False
        return not self.actual_end or moment <= self.actual_end

    def time_left(self, moment: datetime) -> timedelta | None:
        """The time left to work in it at that moment.

        All of it before it starts, up to its planned end while in progress, never below 0, and none once it has ended.
        None without its dates.
        """
        if not self.duration:
            return None
        match self.state:
            case SprintState.NOT_STARTED:
                return self.duration
            case SprintState.IN_PROGRESS:
                assert self.planned_end
                return max(self.planned_end - moment, timedelta())
            case SprintState.ENDED:
                return timedelta()


@dataclass(frozen=True, kw_only=True)
class Comment:
    """The author is the source's identity for them, or None if the source has none."""

    author: str | None
    created: datetime
    body: str


@dataclass(frozen=True, kw_only=True)
class Attachment:
    id: str
    filename: str
    size: int
    created: datetime


@dataclass(frozen=True, kw_only=True)
class TicketSummary:
    """A ticket as another ticket mentions it, through a link, its parent or a child."""

    source: str
    key: str
    title: str
    status: str
    type: str


@dataclass(frozen=True, kw_only=True)
class Link:
    """Reads as a sentence: "from_key relation to_key", in the source's direction and wording."""

    from_key: str
    relation: str
    to_key: str


@dataclass(frozen=True, kw_only=True)
class Change:
    """One change to one of our fields, or to a link. Values are as the source words them."""

    field: str
    author: str | None
    before: str | None
    after: str | None
    date: datetime


@dataclass(frozen=True, kw_only=True)
class Ticket:
    """A ticket as its source has it, with the tickets it mentions and its Changes, oldest first.

    People are the source's identities for them.
    """

    source: str
    key: str
    space: str
    title: str
    type: str
    status: str
    created: datetime
    updated: datetime
    description: str | None = None
    labels: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    assignee: str | None = None
    points: float | None = None
    estimated_hours: float | None = None
    sprints: tuple[Sprint, ...] = ()
    custom_fields: dict[str, CustomValue] = field(default_factory=dict[str, CustomValue])
    comments: tuple[Comment, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    parent: str | None = None
    """The parent's key."""
    children: tuple[TicketSummary, ...] = ()
    links: tuple[Link, ...] = ()
    related_summaries: tuple[TicketSummary, ...] = ()
    """The tickets its parent and links name, as they are now."""
    changes: tuple[Change, ...] = ()

    def as_of(self, when: datetime) -> 'Ticket':
        """The ticket as it was at that moment, undoing the Changes after it.

        Returns:
            A copy with the status, points, estimated hours and Changes it had then. Sprints stay as they are, as
            Changes only name them.
        """
        later = [change for change in self.changes if change.date > when]
        status, points, estimated_hours = self.status, self.points, self.estimated_hours
        for change in reversed(later):
            match change.field:
                case 'status':
                    status = change.before or status
                case 'points':
                    points = _number(change.before)
                case 'estimated_hours':
                    estimated_hours = _number(change.before)
                case _:
                    pass
        changes = self.changes[: len(self.changes) - len(later)]
        return replace(self, status=status, points=points, estimated_hours=estimated_hours, changes=changes)

    def sprint_names_as_of(self, when: datetime) -> set[str]:
        """Names of the sprints holding the ticket then."""
        names = {sprint.name for sprint in self.sprints}
        for change in reversed(self.changes):
            if change.date <= when:
                break
            if change.field == 'sprints':
                names = _sprint_names(change.before)
        return names

    def was_in_sprint(self, name: str) -> bool:
        """Whether the sprint with that name holds or ever held the ticket."""
        return name in {sprint.name for sprint in self.sprints} or any(
            name in _sprint_names(change.before) | _sprint_names(change.after)
            for change in self.changes
            if change.field == 'sprints'
        )


def key_order(key: str) -> tuple[str | int, ...]:
    """Sorts keys as their sources do, with SAT-8 before SAT-10."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r'(\d+)', key))


def _number(value: str | None) -> float | None:
    return float(value) if value else None


def _sprint_names(value: str | None) -> set[str]:
    return set(value.split(_SPRINT_NAMES_SEPARATOR)) if value else set()
