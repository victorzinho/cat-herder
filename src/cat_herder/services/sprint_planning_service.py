from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from itertools import islice

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config, Person, Project, TicketSourceConfig
from cat_herder.domain.sprint_estimate import reestimated_by, sprint_estimate
from cat_herder.domain.sprint_snapshot import SprintPart, SprintSnapshot, SprintTicket, TicketOutcome
from cat_herder.domain.ticket import Sprint, SprintState, Ticket, TicketState, key_order
from cat_herder.domain.time_entry import Hours, TimeEntry
from cat_herder.domain.workload import Workload, weighted_non_ticket_percent
from cat_herder.store.sprint_repository import SprintRepository
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository

# amount of sprints to consider for calculating previous non-ticket hours percentage
_NON_TICKET_SPRINTS = 3


class SprintPlanningService:
    def __init__(self, config: Config, session: Session) -> None:
        self._config = config
        self._default_non_ticket_percent = config.default_non_ticket_percent or 0
        self._sprint_repository = SprintRepository(session)
        self._ticket_repository = TicketRepository(session)
        self._time_entry_repository = TimeEntryRepository(session)

    def snapshot(self, sprint: Sprint) -> SprintSnapshot:
        """The sprint as it was at its end, or as it is now if it hasn't ended.

        Its projects are those of the tickets it held at any point, and those of the entries naming it.
        Its people in a project are whoever has capacity or hours in it, and, until the sprint ends, whoever is
        assigned one of the tickets it holds.
        Entries logged after the moment count in nothing, unless they name the sprint.
        """
        as_of = sprint.actual_end or datetime.now(UTC)
        time_left = sprint.time_left(as_of)
        fraction_left = time_left / sprint.duration if time_left is not None and sprint.duration else None
        ended_sprints = self._sprint_repository.find_ended(sprint.source)

        projects: list[SprintPart] = []
        for project in self._config.projects:
            tickets = self._tickets(sprint, project)
            entries = self._entries(sprint, as_of, project)
            if _takes_part_in_sprint(sprint, tickets, entries or ()):
                projects.append(self._project_part(
                    sprint=sprint,
                    as_of=as_of,
                    fraction_left=fraction_left,
                    non_ticket_percent=self._non_ticket_percent(ended_sprints, tickets, entries),
                    project=project,
                    tickets=tickets,
                    entries=entries,
                ))
        return SprintSnapshot(
            sprint=sprint,
            as_of=as_of,
            time_left=time_left,
            projects=tuple(projects),
            total=self._total_part(sprint, fraction_left, projects),
        )

    def _tickets(self, sprint: Sprint, project: Project) -> list[Ticket]:
        # The project's tickets in the sprint's source, in key order.
        if not project.tickets or project.tickets.source != sprint.source:
            return []
        return sorted(self._ticket_repository.find([project.tickets]), key=lambda ticket: key_order(ticket.key))

    def _entries(self, sprint: Sprint, as_of: datetime, project: Project) -> list[TimeEntry] | None:
        # The project's entries logged by the moment or naming the sprint. None without a time source.
        if not project.time:
            return None
        entries = self._time_entry_repository.find(project.time)
        return [entry for entry in entries if entry.start <= as_of or entry.sprint == sprint.name]

    def _non_ticket_percent(
        self, ended_sprints: Sequence[Sprint], tickets: Sequence[Ticket], entries: Sequence[TimeEntry] | None
    ) -> float:
        # estimation of percentage of hours dedicated to non-ticket tasks, such as ceremonies
        if entries is None:
            return self._default_non_ticket_percent
        taken_part = (sprint for sprint in ended_sprints if _takes_part_in_sprint(sprint, tickets, entries))
        last = islice(taken_part, _NON_TICKET_SPRINTS)
        hours = sum((Hours.of(_entries_in_sprint(sprint, tickets, entries)) for sprint in last), Hours())
        return self._default_non_ticket_percent if hours.others_percent is None else hours.others_percent

    def _project_part(
        self,
        *,
        sprint: Sprint,
        as_of: datetime,
        fraction_left: float | None,
        non_ticket_percent: float,
        project: Project,
        tickets: Sequence[Ticket],
        entries: Sequence[TimeEntry] | None,
    ) -> SprintPart:
        entries_in_sprint = _entries_in_sprint(sprint, tickets, entries) if entries is not None else None
        rows = tuple(
            self._sprint_ticket(sprint, as_of, ticket, entries, entries_in_sprint)
            for ticket in tickets if ticket.was_in_sprint(sprint)
        )
        hours = Hours.of_nullable(entries_in_sprint)
        hours_by_person = self._hours_by_person(entries_in_sprint)
        people_with_capacity = {
            person.slug for person in self._config.people if project.slug in person.hours_by_project
        }
        holders: set[str] = set()
        if sprint.state != SprintState.ENDED:
            holders = {row.assignee for row in rows if row.assignee and row.outcome}
        people = tuple(Workload(
            person=name,
            project=project.slug,
            capacity=self._capacity(sprint, name, project.slug),
            fraction_left=fraction_left,
            non_ticket_percent=non_ticket_percent,
            hours_done=None if hours is None else hours_by_person.get(name, 0),
            work_left=sum(row.hours_left or 0 for row in rows if row.assignee == name),
        ) for name in sorted(people_with_capacity | hours_by_person.keys() | holders))
        everyone = Workload.of_everyone(
            people,
            project=project.slug,
            fraction_left=fraction_left,
            non_ticket_percent=non_ticket_percent,
            hours_done=None if hours is None else hours.total,
            work_left=sum(row.hours_left or 0 for row in rows),
        )
        return SprintPart(project=project.slug, tickets=rows, hours=hours, everyone=everyone, people=people)

    def _total_part(self, sprint: Sprint, fraction_left: float | None, projects: Sequence[SprintPart]) -> SprintPart:
        # A person's capacity is their own, not the sum of their projects', and the share of it set aside for non-ticket
        # work is their projects', weighted by their capacity in each. Hours add up the projects with a time source.
        with_hours = [project.hours for project in projects if project.hours is not None]
        hours = sum(with_hours, Hours()) if with_hours else None
        names = sorted({person.person for project in projects for person in project.people if person.person})
        people: list[Workload] = []
        for name in names:
            in_projects = [person for project in projects for person in project.people if person.person == name]
            non_ticket_percent = weighted_non_ticket_percent(in_projects)
            if non_ticket_percent is None:
                non_ticket_percent = self._default_non_ticket_percent
            people.append(Workload(
                person=name,
                project=None,
                capacity=self._capacity(sprint, name),
                fraction_left=fraction_left,
                non_ticket_percent=non_ticket_percent,
                hours_done=None if hours is None else sum(person.hours_done or 0 for person in in_projects),
                work_left=sum(person.work_left for person in in_projects),
            ))
        everyone = Workload.of_everyone(
            people,
            project=None,
            fraction_left=fraction_left,
            hours_done=None if hours is None else hours.total,
            work_left=sum(project.everyone.work_left for project in projects),
        )
        return SprintPart(
            project=None,
            tickets=tuple(ticket for project in projects for ticket in project.tickets),
            hours=hours,
            everyone=everyone,
            people=tuple(people),
        )

    def _sprint_ticket(
        self,
        sprint: Sprint,
        as_of: datetime,
        ticket: Ticket,
        entries: Sequence[TimeEntry] | None,
        counted: Sequence[TimeEntry] | None,
    ) -> SprintTicket:
        # entries are all the project's, and counted those counting in the sprint, both None without a time source.
        source = self._config.ticket_source(sprint.source)
        then = ticket.as_of(as_of)
        return SprintTicket(
            key=ticket.key,
            assignee=self._config.person_name(ticket.source, ticket.assignee) if ticket.assignee else None,
            status=then.status,
            points=then.points,
            estimate=sprint_estimate(ticket, sprint, as_of, entries or ()),
            reestimated_by=reestimated_by(ticket, sprint, as_of, entries or ()),
            hours=None if counted is None else sum(entry.hours for entry in counted if entry.ticket_key == ticket.key),
            outcome=_outcome(sprint, source, then) if ticket.in_sprint_as_of(sprint, as_of) else None,
            blocked_by=source.open_blockers(ticket),
        )

    def _capacity(self, sprint: Sprint, name: str, project_slug: str | None = None) -> float | None:
        # Their capacity for the sprint, in a project or in total. 0 for someone unknown, and None without its dates.
        if not sprint.duration:
            return None
        person = self._person(name)
        return person.capacity(sprint.duration, project_slug) if person else 0

    def _hours_by_person(self, entries: Iterable[TimeEntry] | None) -> dict[str, float]:
        hours: defaultdict[str, float] = defaultdict(float)
        for entry in entries or ():
            hours[self._config.person_name(entry.source, entry.person)] += entry.hours
        return hours

    def _person(self, name: str) -> Person | None:
        return next((person for person in self._config.people if person.slug == name), None)


def _takes_part_in_sprint(sprint: Sprint, tickets: Iterable[Ticket], entries: Iterable[TimeEntry]) -> bool:
    any_ticket_in_sprint = any(ticket.was_in_sprint(sprint) for ticket in tickets)
    any_entry_in_sprint = any(entry.sprint == sprint.name for entry in entries)
    return any_ticket_in_sprint or any_entry_in_sprint


def _entries_in_sprint(sprint: Sprint, tickets: Iterable[Ticket], entries: Iterable[TimeEntry]) -> list[TimeEntry]:
    keys = {ticket.key for ticket in tickets if ticket.was_in_sprint(sprint)}
    return [entry for entry in entries if entry.counts_in_sprint(sprint, keys)]


def _outcome(sprint: Sprint, source: TicketSourceConfig, ticket: Ticket) -> TicketOutcome:
    match source.state(ticket.status):
        case TicketState.OPEN:
            return TicketOutcome.OPEN
        case TicketState.DISCARDED:
            return TicketOutcome.DISCARDED
        case TicketState.DONE:
            done = source.done_date(ticket)
            return TicketOutcome.DONE if done and sprint.covers(done) else TicketOutcome.DONE_BEFORE
