from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from cat_herder.domain.ticket import Ticket, TicketState, key_order
from cat_herder.domain.time_entry import TimeEntry

# How far hours assigned can be from a capacity for tickets without it being a problem, unless the config says.
DEFAULT_CAPACITY_MARGIN_HOURS = 1


class WriteNotAllowed(Exception):
    """The config gives the source read-only access."""


class Access(StrEnum):
    """Permission checked before running an operation on a source."""

    READ_ONLY = 'read-only'
    FULL = 'full'


@dataclass(frozen=True, kw_only=True)
class EnvCredential:
    """A credential read from an environment variable."""

    name: str


@dataclass(frozen=True, kw_only=True)
class CommandCredential:
    """A credential printed by a command, such as a secret store's CLI."""

    command: str


type Credential = EnvCredential | CommandCredential


@dataclass(frozen=True, kw_only=True)
class SourceSummary:
    """A source's kind, such as jira, and what cat-herder may do in it."""

    slug: str
    type: str
    access: Access


@dataclass(frozen=True, kw_only=True)
class SourceConfig:
    """What every source has, whatever its kind."""

    type: ClassVar[str]
    slug: str
    access: Access
    fetch_window_seconds: int

    def summary(self) -> SourceSummary:
        return SourceSummary(slug=self.slug, type=self.type, access=self.access)


@dataclass(frozen=True, kw_only=True)
class TicketSourceConfig(SourceConfig):
    """What every ticket source has. Statuses and relations are the source's own names."""

    done_statuses: tuple[str, ...]
    discarded_statuses: tuple[str, ...] = ()
    blocking_relation: str | None = None

    def done_date(self, ticket: Ticket) -> datetime | None:
        """When the ticket was done.

        Returns:
            The date of its last Change into a done status, or its creation if there's none. None if it isn't done.
        """
        if ticket.status not in self.done_statuses:
            return None
        into_done = [
            change.date for change in ticket.changes if change.field == 'status' and change.after in self.done_statuses
        ]
        return into_done[-1] if into_done else ticket.created

    def state(self, status: str) -> TicketState:
        """Where a ticket with that status stands."""
        if status in self.done_statuses:
            return TicketState.DONE
        if status in self.discarded_statuses:
            return TicketState.DISCARDED
        return TicketState.OPEN

    def open_blockers(self, ticket: Ticket) -> tuple[str, ...]:
        """The keys of the open tickets blocking it, through blocking_relation, in key order.

        None without blocking_relation. A blocker the ticket doesn't know the status of counts as open.
        """
        if not self.blocking_relation:
            return ()
        status_by_key = {related.key: related.status for related in ticket.related_summaries}
        blockers = {
            link.from_key
            for link in ticket.links
            if link.relation == self.blocking_relation
            and link.to_key == ticket.key
            and self.state(status_by_key.get(link.from_key, '')) == TicketState.OPEN
        }
        return tuple(sorted(blockers, key=key_order))


@dataclass(frozen=True, kw_only=True)
class TimeSourceConfig(SourceConfig):
    """What every time source has. Entries before history_from are never fetched."""

    history_from: datetime


@dataclass(frozen=True, kw_only=True)
class JiraSourceConfig(TicketSourceConfig):
    """A Jira Cloud instance. A field ID left as None doesn't exist in this instance."""

    type: ClassVar[str] = 'jira'
    url: str
    points_field: str | None = None
    sprints_field: str | None = None
    custom_fields: dict[str, str] = field(default_factory=dict[str, str])
    email: Credential
    token: Credential


@dataclass(frozen=True, kw_only=True)
class TogglSourceConfig(TimeSourceConfig):
    """A Toggl Track workspace."""

    type: ClassVar[str] = 'toggl'
    workspace: int
    token: Credential


@dataclass(frozen=True, kw_only=True)
class Person:
    """Capacities are hours per week, and a missing one is 0."""

    slug: str
    identity_by_source: dict[str, str | int]
    weekly_hours: float = 0
    hours_by_project: dict[str, float] = field(default_factory=dict[str, float])

    def capacity(self, period: timedelta, project_slug: str | None = None) -> float:
        """Hours they can work in that period, optionally for a given project."""
        weekly_hours = self.hours_by_project.get(project_slug, 0) if project_slug else self.weekly_hours
        return weekly_hours * (period / timedelta(weeks=1))


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
class ConfigPart:
    """Some projects, with their repositories and a summary of the sources they use."""

    sources: tuple[SourceSummary, ...]
    repositories: tuple[Repository, ...]
    projects: tuple[Project, ...]


@dataclass(frozen=True, kw_only=True)
class Config:
    data_dir: Path
    sources: tuple[SourceConfig, ...]
    projects: tuple[Project, ...]
    people: tuple[Person, ...] = ()
    repositories: tuple[Repository, ...] = ()
    default_non_ticket_percent: float | None = None
    capacity_margin_hours: float = DEFAULT_CAPACITY_MARGIN_HOURS

    def source(self, slug: str) -> SourceConfig:
        """The source with that slug.

        Raises:
            KeyError: if no source has that slug.
        """
        return _by_slug(self.sources, slug)

    def ticket_source(self, slug: str) -> TicketSourceConfig:
        """The ticket source with that slug.

        Raises:
            KeyError: if no ticket source has that slug.
        """
        source = self.source(slug)
        if not isinstance(source, TicketSourceConfig):
            raise KeyError(slug)
        return source

    def time_source(self, slug: str) -> TimeSourceConfig:
        """The time source with that slug.

        Raises:
            KeyError: if no time source has that slug.
        """
        source = self.source(slug)
        if not isinstance(source, TimeSourceConfig):
            raise KeyError(slug)
        return source

    def project(self, slug: str) -> Project:
        """The project with that slug.

        Raises:
            KeyError: if no project has that slug.
        """
        return _by_slug(self.projects, slug)

    def for_project(self, slug: str) -> ConfigPart:
        """That project, with its repositories and the sources it uses.

        Raises:
            KeyError: if no project has that slug.
        """
        return self._for_projects((self.project(slug),), ())

    def for_repository(self, slug: str) -> ConfigPart:
        """The projects with that repository, with their repositories and that one, and the sources they use."""
        projects = tuple(project for project in self.projects if slug in project.repositories)
        return self._for_projects(projects, (slug,))

    def check_writable(self, source: str) -> None:
        """Check the config lets cat-herder write to the source, before contacting it.

        Raises:
            WriteNotAllowed: if the config gives the source read-only access.
        """
        if self.source(source).access is not Access.FULL:
            raise WriteNotAllowed(f'{source} is read-only in the config')

    def person(self, slug: str) -> Person:
        """The person with that slug.

        Raises:
            KeyError: if no person has that slug.
        """
        return _by_slug(self.people, slug)

    def person_name(self, source: str, identity: str | None) -> str:
        """The name to show for the person with that identity in the source.

        Returns:
            Their slug, "unknown (<identity>)" if no person has that identity, or "unknown" without an identity.
        """
        if identity is None:
            return 'unknown'
        person = next(
            (person for person in self.people if str(person.identity_by_source.get(source)) == identity), None
        )
        return person.slug if person else f'unknown ({identity})'

    def project_of_ticket(self, ticket: Ticket) -> Project | None:
        """The project the ticket's space belongs to, if any."""
        origin = TicketOrigin(source=ticket.source, space=ticket.space)
        return next((project for project in self.projects if project.tickets == origin), None)

    def project_of_time_entry(self, entry: TimeEntry) -> Project | None:
        """The project the entry's space belongs to, if any."""
        return next(
            (
                project
                for project in self.projects
                if project.time and project.time.source == entry.source and entry.space in project.time.spaces
            ),
            None,
        )

    def ticket_origins(self, project_slugs: Collection[str] = ()) -> list[TicketOrigin]:
        """The ticket origins of those projects, or of every project, each once, sorted by source and space."""
        origins = {
            project.tickets
            for project in self.projects
            if project.tickets and (not project_slugs or project.slug in project_slugs)
        }
        return sorted(origins, key=lambda origin: (origin.source, origin.space))

    def ticket_sources(self) -> tuple[str, ...]:
        """Slugs of the ticket sources."""
        return tuple(source.slug for source in self.sources if isinstance(source, TicketSourceConfig))

    def ticket_sources_for_key_prefix(self, prefix: str) -> tuple[str, ...]:
        """The ticket sources a key with this prefix can come from, such as SAT for SAT-7.

        The prefix is a space's name, and each source names its own spaces, so two sources can both have a SAT.
        With projects sat (jira, SAT) and sat-meteo (other, SAT), SAT gives ('jira', 'other'), and a WEB only in jira
        gives ('jira',). A prefix that no project uses can come from any ticket source, so it gives all of them.
        """
        in_projects = {
            project.tickets.source for project in self.projects if project.tickets and project.tickets.space == prefix
        }
        return tuple(sorted(in_projects)) or self.ticket_sources()

    def _for_projects(self, projects: tuple[Project, ...], repository_slugs: tuple[str, ...]) -> ConfigPart:
        sources = {origin.source for project in projects for origin in (project.tickets, project.time) if origin}
        repository_slugs = (*repository_slugs, *(slug for project in projects for slug in project.repositories))
        return ConfigPart(
            sources=tuple(source.summary() for source in self.sources if source.slug in sources),
            repositories=tuple(repository for repository in self.repositories if repository.slug in repository_slugs),
            projects=projects,
        )


class _Slugged(Protocol):
    @property
    def slug(self) -> str: ...


def _by_slug[Item: _Slugged](items: tuple[Item, ...], slug: str) -> Item:
    for item in items:
        if item.slug == slug:
            return item
    raise KeyError(slug)
