from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, Project, TicketSourceConfig
from cat_herder.domain.ticket import Sprint, Ticket, key_order
from cat_herder.domain.time_entry import TimeEntry
from cat_herder.services.reports_types import (
    EndedSprintReport,
    Hours,
    ProjectReport,
    SprintFigures,
    SprintOutcome,
    SprintPerson,
    SprintProject,
    SprintTicket,
    TicketCount,
)
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository

# How long after a sprint starts its tickets' estimates can still change without counting as re-estimates.
_PLANNING_MARGIN = timedelta(hours=24)


class ReportsService:
    """Reports from the local copy, which the caller syncs first."""

    def __init__(self, config: Config, session: Session) -> None:
        self._config = config
        self._ticket_repository = TicketRepository(session)
        self._time_entry_repository = TimeEntryRepository(session)

    def project_report(
        self, project_slug: str, start: datetime | None = None, end: datetime | None = None
    ) -> ProjectReport:
        """The report for the specified project slug in the given time range.

        Raises:
            KeyError: if no project has that slug.
        """
        project = self._config.project(project_slug)
        points = 0.0
        hours = None

        if project.tickets:
            source = self._config.ticket_source(project.tickets.source)
            tickets = self._ticket_repository.find([project.tickets])
            points = sum(_get_done_ticket_points(source, ticket, start, end) for ticket in tickets)

        if project.time:
            time_entries = self._time_entry_repository.find(project.time, start=start, end=end)
            hours = Hours.of(time_entries)

        return ProjectReport(points=points, hours=hours)

    def ended_sprint_report(self, sprint: Sprint) -> EndedSprintReport:
        """Returns a report of an ended sprint.

        Its projects are those of the tickets it held at any point, and those of the entries naming it.
        """
        assert sprint.duration and sprint.actual_end
        all_tickets = self._ticket_repository.find(origins=[
            project.tickets
            for project in self._config.projects
            if project.tickets and project.tickets.source == sprint.source
        ])
        tickets = [ticket for ticket in all_tickets if ticket.was_in_sprint(sprint.name)]
        tickets.sort(key=lambda ticket: key_order(ticket.key))
        tickets_by_project: defaultdict[str, list[Ticket]] = defaultdict(list)
        for ticket in tickets:
            if project := self._config.project_of_ticket(ticket):
                tickets_by_project[project.slug].append(ticket)
        entries_by_project = {
            project.slug: self._time_entry_repository.find(project.time)
            for project in self._config.projects
            if project.time
        }


        def has_tickets_or_time_entries(project : Project):
            return tickets_by_project[project.slug] or any(
                entry.sprint == sprint.name for entry in entries_by_project.get(project.slug, ())
            )

        projects = [
            self._sprint_project(sprint, prj, tickets_by_project[prj.slug], entries_by_project.get(prj.slug))
            for prj in self._config.projects if has_tickets_or_time_entries(prj)
        ]
        return EndedSprintReport(sprint=sprint, projects=tuple(projects), total=self._sprint_total(sprint, projects))

    def _sprint_project(
        self, sprint: Sprint, project: Project, tickets: Sequence[Ticket], entries: Sequence[TimeEntry] | None
    ) -> SprintProject:
        # entries are all the project's, or None without a time source.
        keys = {ticket.key for ticket in tickets}
        entries_in_sprint = None if entries is None else [
            entry for entry in entries if entry.counts_in_sprint(sprint, keys)
        ]
        rows = tuple(_sprint_ticket(sprint, ticket, entries, entries_in_sprint) for ticket in tickets)
        people = self._sprint_people(sprint, project, entries_in_sprint)
        return SprintProject(
            project=project.slug,
            capacity=sum(person.capacity for person in people),
            estimate=sum(row.estimate or 0 for row in rows),
            reestimated_by=sum(row.reestimated_by for row in rows),
            hours=Hours.of(entries_in_sprint) if entries_in_sprint is not None else None,
            outcome=_outcome(sprint, self._config.ticket_source(sprint.source), tickets),
            people=people,
            tickets=rows,
        )

    def _sprint_people(
        self, sprint: Sprint, project: Project, counted: Sequence[TimeEntry] | None
    ) -> tuple[SprintPerson, ...]:
        # Whoever has capacity in the project or hours counted in it.
        assert sprint.duration
        capacity_by_person = {
            person.slug: person.capacity(sprint.duration, project.slug)
            for person in self._config.people
            if project.slug in person.hours_by_project
        }
        hours_by_person: defaultdict[str, float] = defaultdict(float)
        for entry in counted or ():
            hours_by_person[self._config.person_name(entry.source, entry.person)] += entry.hours
        return tuple(
            SprintPerson(
                person=name,
                capacity=capacity_by_person.get(name, 0),
                hours=None if counted is None else hours_by_person.get(name, 0),
            )
            for name in sorted(capacity_by_person.keys() | hours_by_person.keys())
        )

    def _sprint_total(self, sprint: Sprint, projects: Sequence[SprintProject]) -> SprintFigures:
        # People's capacity is their own, not the sum of their projects'. Hours add up the projects with a time source.
        assert sprint.duration
        person_by_slug = {person.slug: person for person in self._config.people}
        with_hours = [project for project in projects if project.hours]
        hours_by_person: defaultdict[str, float] = defaultdict(float)
        for project in projects:
            for person in project.people:
                hours_by_person[person.person] += person.hours or 0
        people = tuple(
            SprintPerson(
                person=name,
                capacity=person_by_slug[name].capacity(sprint.duration) if name in person_by_slug else 0,
                hours=hours_by_person[name] if with_hours else None,
            )
            for name in sorted(hours_by_person)
        )
        outcome = _outcome(sprint, self._config.ticket_source(sprint.source), ())
        for project in projects:
            outcome += project.outcome
        return SprintFigures(
            capacity=sum(person.capacity for person in people),
            estimate=sum(project.estimate for project in projects),
            reestimated_by=sum(project.reestimated_by for project in projects),
            hours=sum((project.hours for project in with_hours if project.hours), Hours(tickets=0, others=0))
            if with_hours
            else None,
            outcome=outcome,
            people=people,
        )


def _get_done_ticket_points(
    source: TicketSourceConfig, ticket: Ticket, start: datetime | None, end: datetime | None
) -> float:
    done = source.done_date(ticket)
    if done and (not start or done >= start) and (not end or done < end) and ticket.points:
        return ticket.points
    return 0


def _sprint_ticket(
    sprint: Sprint,
    ticket: Ticket,
    all_entries: Sequence[TimeEntry] | None,
    entries_in_sprint: Sequence[TimeEntry] | None
) -> SprintTicket:
    # the estimate leaves out hours logged before the sprint
    # reestimated_by compares it with the ticket state after a "planning period"; changing estimates a few hours
    # after sprint start does not count as a reestimation during the sprint
    assert sprint.start and sprint.actual_end
    hours_before = sum(
        entry.hours for entry in all_entries or () if entry.ticket_key == ticket.key and entry.start < sprint.start
    )
    estimate = _estimate(sprint, ticket, sprint.actual_end, hours_before)
    planned_estimate = _estimate(sprint, ticket, sprint.start + _PLANNING_MARGIN, hours_before)
    at_end = ticket.as_of(sprint.actual_end)
    hours = None if entries_in_sprint is None else sum(
        entry.hours for entry in entries_in_sprint if entry.ticket_key == ticket.key
    )
    return SprintTicket(
        key=ticket.key,
        status=at_end.status,
        points=at_end.points,
        estimate=estimate,
        hours=hours,
        reestimated_by=(estimate or 0) - (planned_estimate or 0),
    )


def _estimate(sprint: Sprint, ticket: Ticket, when: datetime, hours_before: float) -> float | None:
    # 0 if the sprint didn't hold the ticket then, and None if it had no estimate.
    if sprint.name not in ticket.sprint_names_as_of(when):
        return 0
    estimate = ticket.as_of(when).estimated_hours
    return max(estimate - hours_before, 0) if estimate is not None else None


def _outcome(sprint: Sprint, source: TicketSourceConfig, tickets: Iterable[Ticket]) -> SprintOutcome:
    # A ticket done before the sprint counts nowhere.
    assert sprint.actual_end
    done, discarded, open_ = TicketCount(), TicketCount(), TicketCount()
    for ticket in tickets:
        if sprint.name not in ticket.sprint_names_as_of(sprint.actual_end):
            continue
        at_end = ticket.as_of(sprint.actual_end)
        count = TicketCount(tickets=1, points=at_end.points or 0)
        if done_date := source.done_date(at_end):
            done += count if sprint.covers(done_date) else TicketCount()
        elif at_end.status in source.discarded_statuses:
            discarded += count
        else:
            open_ += count
    return SprintOutcome(done=done, discarded=discarded if source.discarded_statuses else None, open=open_)
