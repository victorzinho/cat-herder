from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

type CustomValue = str | float | None


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
    parent: TicketSummary | None = None
    children: tuple[TicketSummary, ...] = ()
    links: tuple[Link, ...] = ()
    linked: tuple[TicketSummary, ...] = ()
    changes: tuple[Change, ...] = ()
