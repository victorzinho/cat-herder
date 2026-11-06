from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class Access(StrEnum):
    """Permission checked before running an operation on a source."""

    READ_ONLY = 'read-only'
    FULL = 'full'


@dataclass(frozen=True, kw_only=True)
class SourceConfig:
    """What every source has, whatever its kind."""

    slug: str
    access: Access
    fetch_window_seconds: int


@dataclass(frozen=True, kw_only=True)
class TicketSourceConfig(SourceConfig):
    """What every ticket source has. Statuses and relations are the source's own names."""

    done_statuses: tuple[str, ...]
    discarded_statuses: tuple[str, ...] = ()
    blocking_relation: str | None = None


@dataclass(frozen=True, kw_only=True)
class TimeSourceConfig(SourceConfig):
    """What every time source has."""


@dataclass(frozen=True, kw_only=True)
class JiraSourceConfig(TicketSourceConfig):
    """A Jira Cloud instance. A field ID left as None doesn't exist in this instance."""

    url: str
    points_field: str | None = None
    sprints_field: str | None = None
    custom_fields: dict[str, str] = field(default_factory=dict[str, str])
    email_env: str
    token_env: str


@dataclass(frozen=True, kw_only=True)
class TogglSourceConfig(TimeSourceConfig):
    """A Toggl Track workspace."""

    workspace: int
    history_from: date
    token_env: str


@dataclass(frozen=True, kw_only=True)
class Person:
    """Capacities are hours per week, and a missing one is 0."""

    slug: str
    identity_by_source: dict[str, str | int]
    weekly_hours: float = 0
    hours_by_project: dict[str, float] = field(default_factory=dict[str, float])


@dataclass(frozen=True, kw_only=True)
class Repository:
    """The path is the main repository's; its worktrees count as the same repository."""

    slug: str
    path: Path


@dataclass(frozen=True, kw_only=True)
class TicketOrigin:
    """The source slug and the space in it."""

    source: str
    space: str


@dataclass(frozen=True, kw_only=True)
class TimeOrigin:
    """The source slug and the space names in it."""

    source: str
    spaces: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Project:
    """Has tickets, time, or both."""

    slug: str
    tickets: TicketOrigin | None
    time: TimeOrigin | None
    repositories: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Config:
    data_dir: Path
    sources: tuple[SourceConfig, ...]
    projects: tuple[Project, ...]
    people: tuple[Person, ...] = ()
    repositories: tuple[Repository, ...] = ()
    default_non_ticket_percent: float | None = None

    def source(self, slug: str) -> SourceConfig:
        return _by_slug(self.sources, slug)

    def project(self, slug: str) -> Project:
        return _by_slug(self.projects, slug)


class _Slugged(Protocol):
    @property
    def slug(self) -> str: ...


def _by_slug[Item: _Slugged](items: tuple[Item, ...], slug: str) -> Item:
    for item in items:
        if item.slug == slug:
            return item
    raise KeyError(slug)
