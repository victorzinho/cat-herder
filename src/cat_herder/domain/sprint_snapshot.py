from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from cat_herder.domain.ticket import Sprint
from cat_herder.domain.time_entry import HOURS_TOLERANCE, Hours
from cat_herder.domain.workload import Workload


class TicketOutcome(StrEnum):
    OPEN = 'open'
    DONE = 'done'  # during the sprint
    DONE_BEFORE = 'done before'  # before the sprint
    DISCARDED = 'discarded'


@dataclass(frozen=True, kw_only=True)
class SprintTicket:
    key: str
    assignee: str | None
    status: str
    points: float | None
    estimate: float | None
    reestimated_by: float
    hours: float | None  # already logged
    outcome: TicketOutcome | None
    blocked_by: tuple[str, ...]

    @property
    def delta(self) -> float | None:
        """Hours minus estimate. None without a time source or an estimate."""
        return self.hours - self.estimate if self.hours is not None and self.estimate is not None else None

    @property
    def hours_left(self) -> float | None:
        """Never below 0."""
        if self.outcome != TicketOutcome.OPEN:
            return 0
        return None if self.estimate is None else max(self.estimate - (self.hours or 0), 0)

    @property
    def exceeds_estimate(self) -> bool:
        return (self.delta or 0) > HOURS_TOLERANCE


@dataclass(frozen=True, kw_only=True)
class SprintPart:
    """One of the sprint's projects, or the whole sprint when project is None."""

    project: str | None
    tickets: tuple[SprintTicket, ...]
    hours: Hours | None
    everyone: Workload
    people: tuple[Workload, ...]


@dataclass(frozen=True, kw_only=True)
class Blocked:
    key: str
    by: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class SprintProblems:
    """What threatens a sprint that hasn't ended."""

    wont_fit: tuple[Workload, ...]
    spare_capacity: tuple[Workload, ...]
    capacity_exceeded: tuple[Workload, ...]
    estimate_exceeded: tuple[SprintTicket, ...]
    unassigned: tuple[SprintTicket, ...]
    no_estimate: tuple[SprintTicket, ...]
    blocked_in_sprint: tuple[Blocked, ...]
    blocked_outside: tuple[Blocked, ...]


@dataclass(frozen=True, kw_only=True)
class SprintSnapshot:
    """A sprint as it was at as_of, in each of its projects and in total."""

    sprint: Sprint
    as_of: datetime
    time_left: timedelta | None
    projects: tuple[SprintPart, ...]
    total: SprintPart

    @property
    def workloads(self) -> tuple[Workload, ...]:
        """Everyone's in the sprint, then in each project, then each person's in the sprint, then in each project."""
        return (
            self.total.everyone,
            *(project.everyone for project in self.projects),
            *self.total.people,
            *(person for project in self.projects for person in project.people),
        )

    @property
    def open_tickets(self) -> tuple[SprintTicket, ...]:
        return tuple(ticket for ticket in self.total.tickets if ticket.outcome == TicketOutcome.OPEN)

    def wont_fit(self, margin_hours: float) -> tuple[Workload, ...]:
        """The workloads with more work left than capacity for tickets left, by more than the margin.

        None without the sprint's dates.
        """
        return tuple(workload for workload in self.workloads if workload.wont_fit(margin_hours))

    def spare_capacity(self, margin_hours: float) -> tuple[Workload, ...]:
        """The workloads with less work left than capacity for tickets left, by more than the margin.

        None without the sprint's dates.
        """
        return tuple(workload for workload in self.workloads if workload.has_spare_capacity(margin_hours))

    @property
    def capacity_exceeded(self) -> tuple[Workload, ...]:
        """The workloads with more hours done than their capacity for the whole sprint."""
        return tuple(workload for workload in self.workloads if workload.exceeds_capacity)

    @property
    def estimate_exceeded(self) -> tuple[SprintTicket, ...]:
        """The open tickets with more hours than their estimate."""
        return tuple(ticket for ticket in self.open_tickets if ticket.exceeds_estimate)

    @property
    def unassigned(self) -> tuple[SprintTicket, ...]:
        """The open tickets with no assignee."""
        return tuple(ticket for ticket in self.open_tickets if not ticket.assignee)

    @property
    def no_estimate(self) -> tuple[SprintTicket, ...]:
        """The open tickets with no estimate."""
        return tuple(ticket for ticket in self.open_tickets if ticket.estimate is None)

    @property
    def blocked_in_sprint(self) -> tuple[Blocked, ...]:
        """The open tickets blocked by tickets the sprint holds, with those."""
        return self._blocked(by_tickets_in_sprint=True)

    @property
    def blocked_outside(self) -> tuple[Blocked, ...]:
        """The open tickets blocked by tickets the sprint doesn't hold, with those."""
        return self._blocked(by_tickets_in_sprint=False)

    def problems(self, margin_hours: float) -> SprintProblems:
        """Everything that threatens the sprint, with that margin for capacity."""
        return SprintProblems(
            wont_fit=self.wont_fit(margin_hours),
            spare_capacity=self.spare_capacity(margin_hours),
            capacity_exceeded=self.capacity_exceeded,
            estimate_exceeded=self.estimate_exceeded,
            unassigned=self.unassigned,
            no_estimate=self.no_estimate,
            blocked_in_sprint=self.blocked_in_sprint,
            blocked_outside=self.blocked_outside,
        )

    def _blocked(self, by_tickets_in_sprint: bool) -> tuple[Blocked, ...]:
        in_sprint = {ticket.key for ticket in self.total.tickets if ticket.outcome}
        blocked: list[Blocked] = []
        for ticket in self.open_tickets:
            if blockers := tuple(key for key in ticket.blocked_by if (key in in_sprint) == by_tickets_in_sprint):
                blocked.append(Blocked(key=ticket.key, by=blockers))
        return tuple(blocked)
