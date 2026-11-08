from collections.abc import Iterable
from datetime import datetime, timedelta

from cat_herder.domain.ticket import Sprint, Ticket
from cat_herder.domain.time_entry import TimeEntry

# How long after a sprint starts its tickets' estimates can still change without counting as re-estimates.
PLANNING_MARGIN = timedelta(hours=24)


def sprint_estimate(ticket: Ticket, sprint: Sprint, when: datetime, entries: Iterable[TimeEntry]) -> float | None:
    """The hours the ticket was estimated to take in the sprint at that moment.

    That's its estimate then, minus the hours logged on it before the sprint, all of them if the sprint has no start,
    and never below 0. 0 if the sprint didn't hold the ticket then, and None if it had no estimate.
    """
    if not ticket.in_sprint_as_of(sprint, when):
        return 0
    estimate = ticket.as_of(when).estimated_hours
    if estimate is None:
        return None
    hours_before = sum(
        entry.hours
        for entry in entries
        if entry.ticket_key == ticket.key and (not sprint.start or entry.start < sprint.start)
    )
    return max(estimate - hours_before, 0)


def reestimated_by(ticket: Ticket, sprint: Sprint, when: datetime, entries: Iterable[TimeEntry]) -> float:
    """How much the ticket's sprint estimate changed from the end of planning to that moment.

    Planning ends PLANNING_MARGIN after the sprint starts, so nothing changes before then or without a start. A missing
    estimate counts as 0.
    """
    if not sprint.start:
        return 0
    entries = list(entries)
    planned_at = min(sprint.start + PLANNING_MARGIN, when)
    estimate = sprint_estimate(ticket, sprint, when, entries) or 0
    return estimate - (sprint_estimate(ticket, sprint, planned_at, entries) or 0)
