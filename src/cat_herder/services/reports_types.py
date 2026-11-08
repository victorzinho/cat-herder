from collections.abc import Iterable
from dataclasses import dataclass

from cat_herder.domain.ticket import Sprint
from cat_herder.domain.time_entry import TimeEntry


@dataclass(frozen=True, kw_only=True)
class Hours:
    """Hours on tickets, and the rest: entries with no ticket, flagged ones included."""

    tickets: float
    others: float

    @classmethod
    def of(cls, entries: Iterable[TimeEntry]) -> 'Hours':
        tickets = others = 0.0
        for entry in entries:
            if entry.ticket_key:
                tickets += entry.hours
            else:
                others += entry.hours
        return cls(tickets=tickets, others=others)

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
        """Percent of the hours on no ticket. None without hours."""
        return 100 * self.others / self.total if self.total else None


@dataclass(frozen=True, kw_only=True)
class ProjectReport:
    """Points of the tickets done, and hours, which are None if the project has no time source."""

    points: float
    hours: Hours | None

    @property
    def ticket_speed(self) -> float | None:
        """Points per hour on tickets. None without a time source or hours on tickets."""
        return _speed(self.points, self.hours.tickets if self.hours else None)

    @property
    def total_speed(self) -> float | None:
        """Points per hour, counting hours on no ticket too. None without a time source or hours."""
        return _speed(self.points, self.hours.total if self.hours else None)


@dataclass(frozen=True, kw_only=True)
class TicketCount:
    tickets: int = 0
    points: float = 0

    def __add__(self, other: 'TicketCount') -> 'TicketCount':
        return TicketCount(tickets=self.tickets + other.tickets, points=self.points + other.points)


@dataclass(frozen=True, kw_only=True)
class SprintOutcome:
    """Tickets still in the sprint at its end, by their status then.

    done only counts tickets done during the sprint.
    discarded is None if the source has no discarded statuses.
    """

    done: TicketCount
    discarded: TicketCount | None
    open: TicketCount

    def __add__(self, other: 'SprintOutcome') -> 'SprintOutcome':
        discarded = self.discarded + other.discarded if self.discarded and other.discarded else None
        return SprintOutcome(done=self.done + other.done, discarded=discarded, open=self.open + other.open)


@dataclass(frozen=True, kw_only=True)
class SprintPerson:
    """A person's capacity for the sprint, and their hours in it, which are None without a time source."""

    person: str
    capacity: float
    hours: float | None

    @property
    def delta(self) -> float | None:
        """Hours minus capacity. None without a time source."""
        return self.hours - self.capacity if self.hours is not None else None


@dataclass(frozen=True, kw_only=True)
class SprintTicket:
    """A ticket that was in the sprint at any point, as it was at the sprint's end.

    estimate is 0 if it was no longer in the sprint, and None without one. hours are None without a time source.
    """

    key: str
    status: str
    points: float | None
    estimate: float | None
    hours: float | None
    reestimated_by: float

    @property
    def delta(self) -> float | None:
        """Hours minus estimate. None without a time source or an estimate."""
        return self.hours - self.estimate if self.hours is not None and self.estimate is not None else None


@dataclass(frozen=True, kw_only=True)
class SprintFigures:
    """What a report on an ended sprint gives for each project, and in total. hours are None without a time source."""

    capacity: float
    estimate: float
    reestimated_by: float
    hours: Hours | None
    outcome: SprintOutcome
    people: tuple[SprintPerson, ...]

    @property
    def ticket_speed(self) -> float | None:
        """Done points per hour on tickets. None without a time source or hours on tickets."""
        return _speed(self.outcome.done.points, self.hours.tickets if self.hours else None)

    @property
    def total_speed(self) -> float | None:
        """Done points per hour, counting hours on no ticket too. None without a time source or hours."""
        return _speed(self.outcome.done.points, self.hours.total if self.hours else None)

    @property
    def hours_vs_capacity(self) -> float | None:
        """Total hours minus capacity. None without a time source."""
        return self.hours.total - self.capacity if self.hours else None


@dataclass(frozen=True, kw_only=True)
class SprintProject(SprintFigures):
    project: str
    tickets: tuple[SprintTicket, ...]


@dataclass(frozen=True, kw_only=True)
class EndedSprintReport:
    sprint: Sprint
    projects: tuple[SprintProject, ...]
    total: SprintFigures


def _speed(points: float, hours: float | None) -> float | None:
    return points / hours if hours else None

