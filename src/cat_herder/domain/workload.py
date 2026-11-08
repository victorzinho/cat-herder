from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from cat_herder.domain.time_entry import HOURS_TOLERANCE


@dataclass(frozen=True, kw_only=True)
class Workload:
    """A person's, or everyone's, time and work in one of a sprint's projects, or in the whole sprint."""

    person: str | None
    """None for everyone."""
    project: str | None
    """None for the whole sprint."""
    capacity: float | None
    """Hours they can work in the whole sprint, from their weekly hours. None without the sprint's dates."""
    fraction_left: float | None
    """Fraction of the sprint still ahead: 1 before it starts, 0 once it ends. None without its dates."""
    non_ticket_percent: float | None
    """Percent of capacity set aside for non-ticket work, such as ceremonies."""
    hours_done: float | None
    """Hours already logged in the sprint. None without a time source."""
    work_left: float
    """Hours of work left on their open tickets: estimates minus hours logged. Everyone's count unassigned tickets."""

    @classmethod
    def of_everyone(
        cls,
        people: Sequence['Workload'],
        *,
        project: str | None,
        fraction_left: float | None,
        non_ticket_percent: float | None = None,
        hours_done: float | None,
        work_left: float,
    ) -> 'Workload':
        """Everyone's, adding up the people's capacities.

        Args:
            people: each person's workload, in the same project or in the whole sprint.
            project: the project, or None for the whole sprint.
            fraction_left: the fraction of the sprint still ahead, None without its dates.
            non_ticket_percent: the one they share, as in a project. By default, theirs weighted by capacity.
            hours_done: everyone's hours logged in the sprint, None without a time source.
            work_left: the hours of work left on every open ticket, assigned or not.
        """
        if non_ticket_percent is None:
            non_ticket_percent = weighted_non_ticket_percent(people)
        return cls(
            person=None,
            project=project,
            capacity=None if fraction_left is None else sum(person.capacity or 0 for person in people),
            fraction_left=fraction_left,
            non_ticket_percent=non_ticket_percent,
            hours_done=hours_done,
            work_left=work_left,
        )

    @property
    def capacity_left(self) -> float | None:
        """The hours they can work in the part of the sprint left. None without the sprint's dates."""
        return None if self.capacity is None or self.fraction_left is None else self.capacity * self.fraction_left

    @property
    def ticket_capacity_left(self) -> float | None:
        """The part of capacity_left for tickets. None without the sprint's dates."""
        if self.capacity_left is None:
            return None
        return self.capacity_left * (1 - (self.non_ticket_percent or 0) / 100)

    @property
    def capacity_exceeded_by(self) -> float | None:
        """Hours logged minus capacity, negative while below it. None without a time source or the sprint's dates."""
        return None if self.hours_done is None or self.capacity is None else self.hours_done - self.capacity

    @property
    def wont_fit_by(self) -> float | None:
        """Work left minus capacity for tickets left. None without the sprint's dates."""
        return None if self.ticket_capacity_left is None else self.work_left - self.ticket_capacity_left

    @property
    def spare_capacity_by(self) -> float | None:
        """Capacity for tickets left minus work left. None without the sprint's dates."""
        return None if self.ticket_capacity_left is None else self.ticket_capacity_left - self.work_left

    def wont_fit(self, margin_hours: float) -> bool:
        """Whether the work left is above the capacity for tickets left, by more than the margin."""
        return (self.wont_fit_by or 0) - margin_hours > HOURS_TOLERANCE

    def has_spare_capacity(self, margin_hours: float) -> bool:
        """Whether the work left is below the capacity for tickets left, by more than the margin."""
        return (self.spare_capacity_by or 0) - margin_hours > HOURS_TOLERANCE

    @property
    def exceeds_capacity(self) -> bool:
        """Whether the hours are already above the capacity for the whole sprint."""
        return (self.capacity_exceeded_by or 0) > HOURS_TOLERANCE


def weighted_non_ticket_percent(workloads: Iterable[Workload]) -> float | None:
    """Their non-ticket percents, weighted by their capacity. None without any capacity."""
    weighted = [(workload.capacity or 0, workload.non_ticket_percent or 0) for workload in workloads]
    capacity = sum(weight for weight, _ in weighted)
    return sum(weight * percent for weight, percent in weighted) / capacity if capacity else None
