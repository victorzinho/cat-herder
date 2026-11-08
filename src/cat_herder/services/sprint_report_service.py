from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from cat_herder.domain.config import Config
from cat_herder.domain.sprint_snapshot import SprintPart, SprintProblems, SprintSnapshot, SprintTicket, TicketOutcome
from cat_herder.domain.ticket import Sprint
from cat_herder.domain.time_entry import Hours
from cat_herder.domain.workload import Workload
from cat_herder.services.sprint_planning_service import SprintPlanningService


@dataclass(frozen=True, kw_only=True)
class TicketCount:
    tickets: int = 0
    points: float = 0

    @classmethod
    def of(cls, tickets: Iterable[SprintTicket]) -> 'TicketCount':
        points = [ticket.points or 0 for ticket in tickets]
        return cls(tickets=len(points), points=sum(points))


@dataclass(frozen=True, kw_only=True)
class SprintOutcome:
    done: TicketCount
    discarded: TicketCount | None
    """ None if the source has no discarded statuses """
    open: TicketCount


@dataclass(frozen=True, kw_only=True)
class TicketTotals:
    num: int
    points: float
    estimated_hours: float
    unassigned_hours: float


@dataclass(frozen=True, kw_only=True)
class SprintFigures:
    project: str | None
    """ Totals when project is None. """
    everyone: Workload
    people: tuple[Workload, ...]
    hours: Hours | None
    estimate: float
    reestimated_by: float
    outcome: SprintOutcome
    ticket_totals: TicketTotals
    tickets: tuple[SprintTicket, ...]

    @property
    def open_tickets(self) -> tuple[SprintTicket, ...]:
        return tuple(ticket for ticket in self.tickets if ticket.outcome == TicketOutcome.OPEN)

    @property
    def ticket_speed(self) -> float | None:
        """Done points per hour on tickets. None without a time source or hours on tickets."""
        return self.outcome.done.points / self.hours.tickets if self.hours and self.hours.tickets else None

    @property
    def total_speed(self) -> float | None:
        """Done points per hour, counting hours on no ticket too. None without a time source or hours."""
        return self.outcome.done.points / self.hours.total if self.hours and self.hours.total else None


@dataclass(frozen=True, kw_only=True)
class EndedSprintReport:
    sprint: Sprint
    projects: tuple[SprintFigures, ...]
    total: SprintFigures


@dataclass(frozen=True, kw_only=True)
class PlannedSprintReport:
    sprint: Sprint
    projects: tuple[SprintFigures, ...]
    total: SprintFigures
    problems: SprintProblems


@dataclass(frozen=True, kw_only=True)
class OngoingSprintReport:
    sprint: Sprint
    now: datetime
    time_left: timedelta
    projects: tuple[SprintFigures, ...]
    total: SprintFigures
    problems: SprintProblems


class SprintReportService:
    def __init__(self, config: Config, session: Session) -> None:
        self._config = config
        self._planning_service = SprintPlanningService(config, session)

    def ended_sprint_report(self, sprint: Sprint) -> EndedSprintReport:
        snapshot = self._planning_service.snapshot(sprint)
        return EndedSprintReport(sprint=sprint, projects=self._projects(snapshot), total=self._total(snapshot))

    def planned_sprint_report(self, sprint: Sprint) -> PlannedSprintReport:
        snapshot = self._planning_service.snapshot(sprint)
        return PlannedSprintReport(
            sprint=sprint,
            projects=self._projects(snapshot),
            total=self._total(snapshot),
            problems=snapshot.problems(self._config.capacity_margin_hours),
        )

    def ongoing_sprint_report(self, sprint: Sprint) -> OngoingSprintReport:
        snapshot = self._planning_service.snapshot(sprint)
        assert snapshot.time_left is not None
        return OngoingSprintReport(
            sprint=sprint,
            now=snapshot.as_of,
            time_left=snapshot.time_left,
            projects=self._projects(snapshot),
            total=self._total(snapshot),
            problems=snapshot.problems(self._config.capacity_margin_hours),
        )

    def _projects(self, snapshot: SprintSnapshot) -> tuple[SprintFigures, ...]:
        return tuple(self._figures(snapshot.sprint, project) for project in snapshot.projects)

    def _total(self, snapshot: SprintSnapshot) -> SprintFigures:
        return self._figures(snapshot.sprint, snapshot.total)

    def _figures(self, sprint: Sprint, part: SprintPart) -> SprintFigures:
        def count(outcome: TicketOutcome) -> TicketCount:
            return TicketCount.of(ticket for ticket in part.tickets if ticket.outcome == outcome)

        has_discarded = bool(self._config.ticket_source(sprint.source).discarded_statuses)
        open_tickets = [ticket for ticket in part.tickets if ticket.outcome == TicketOutcome.OPEN]
        return SprintFigures(
            project=part.project,
            everyone=part.everyone,
            people=part.people,
            hours=part.hours,
            estimate=sum(ticket.estimate or 0 for ticket in part.tickets),
            reestimated_by=sum(ticket.reestimated_by for ticket in part.tickets),
            outcome=SprintOutcome(
                done=count(TicketOutcome.DONE),
                discarded=count(TicketOutcome.DISCARDED) if has_discarded else None,
                open=count(TicketOutcome.OPEN),
            ),
            ticket_totals=TicketTotals(
                num=len(open_tickets),
                points=sum(ticket.points or 0 for ticket in open_tickets),
                estimated_hours=sum(ticket.hours_left or 0 for ticket in open_tickets),
                unassigned_hours=sum(ticket.hours_left or 0 for ticket in open_tickets if not ticket.assignee),
            ),
            tickets=part.tickets,
        )
