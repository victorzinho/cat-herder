from collections.abc import Iterable
from dataclasses import dataclass

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

    @property
    def total(self) -> float:
        return self.tickets + self.others

    @property
    def tickets_percent(self) -> float | None:
        """None without hours, as are others_percent."""
        return 100 * self.tickets / self.total if self.total else None

    @property
    def others_percent(self) -> float | None:
        return 100 * self.others / self.total if self.total else None


@dataclass(frozen=True, kw_only=True)
class ProjectReport:
    """Points of the tickets done, and hours, which are None if the project has no time source."""

    points: float
    hours: Hours | None

    @property
    def ticket_speed(self) -> float | None:
        """Points per hour on tickets. None without those hours, as is total_speed."""
        return self.points / self.hours.tickets if self.hours and self.hours.tickets else None

    @property
    def total_speed(self) -> float | None:
        """Points per hour, counting hours on no ticket too."""
        return self.points / self.hours.total if self.hours and self.hours.total else None

