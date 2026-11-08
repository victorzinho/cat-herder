from datetime import timedelta
from typing import Any

from cat_herder.cli.yaml_output import NO_TIME_SOURCE, Block, Flow, dump, hours, number, timestamp
from cat_herder.domain.sprint_snapshot import Blocked, SprintProblems, SprintTicket
from cat_herder.domain.ticket import CustomValue
from cat_herder.domain.workload import Workload
from cat_herder.services.project_report_service import ProjectReport
from cat_herder.services.sprint_report_service import (
    EndedSprintReport,
    OngoingSprintReport,
    PlannedSprintReport,
    SprintFigures,
    TicketCount,
)

SPEED_DECIMALS = 2


def project_report_to_yaml(report: ProjectReport) -> str:
    document = Block(points=number(report.points))
    if report.hours:
        document |= {
            'total_hours': hours(report.hours.total),
            'ticket_hours': hours(report.hours.tickets),
            'ticket_hours_percent': _percent(report.hours.tickets_percent),
            'non_ticket_hours': hours(report.hours.others),
            'non_ticket_hours_percent': _percent(report.hours.others_percent),
            'ticket_speed': _speed(report.ticket_speed),
            'total_speed': _speed(report.total_speed),
        }
    else:
        hours_and_speeds = (
            'total_hours',
            'ticket_hours',
            'ticket_hours_percent',
            'non_ticket_hours',
            'non_ticket_hours_percent',
            'ticket_speed',
            'total_speed',
        )
        document |= dict.fromkeys(hours_and_speeds, NO_TIME_SOURCE)
    return dump(document)


def ended_sprint_report_to_yaml(report: EndedSprintReport) -> str:
    sprint = report.sprint
    assert sprint.start and sprint.actual_end
    return dump(Block({
        'sprint': sprint.name,
        'start': timestamp(sprint.start),
        'end': timestamp(sprint.actual_end),
        'projects': [Block({
            'project': project.project,
            **_ended_figures(project),
            'tickets': [_ended_ticket(ticket) for ticket in project.tickets],
        }) for project in report.projects],
        'total': Block(_ended_figures(report.total)),
    }))


def planned_sprint_report_to_yaml(report: PlannedSprintReport) -> str:
    sprint = report.sprint
    return dump(Block({
        'sprint': sprint.name,
        'start': timestamp(sprint.start) if sprint.start else None,
        'end': timestamp(sprint.planned_end) if sprint.planned_end else None,
        'projects': [Block({
            'project': project.project,
            **_planned_figures(project),
            'tickets': [_planned_ticket(ticket) for ticket in project.open_tickets],
        }) for project in report.projects],
        'total': Block(_planned_figures(report.total)),
        'problems': _problems(report.problems),
    }))


def ongoing_sprint_report_to_yaml(report: OngoingSprintReport) -> str:
    sprint = report.sprint
    assert sprint.start and sprint.planned_end
    return dump(Block({
        'sprint': sprint.name,
        'start': timestamp(sprint.start),
        'end': timestamp(sprint.planned_end),
        'now': timestamp(report.now),
        'time_left': _days_and_hours(report.time_left),
        'projects': [Block({
            'project': project.project,
            **_ongoing_figures(project),
            'tickets': [_ongoing_ticket(ticket) for ticket in project.tickets],
        }) for project in report.projects],
        'total': Block(_ongoing_figures(report.total)),
        'problems': _problems(report.problems),
    }))


def _ended_figures(figures: SprintFigures) -> dict[str, Any]:
    outcome = _closed(figures)
    outcome |= {
        'open': _count(figures.outcome.open),
        'ticket_speed': _or_no_time_source(figures.hours, _speed(figures.ticket_speed)),
        'total_speed': _or_no_time_source(figures.hours, _speed(figures.total_speed)),
        'capacity_exceeded_by': _or_no_time_source(figures.hours, hours(figures.everyone.capacity_exceeded_by)),
    }
    return {
        'planned': _planned(figures),
        'hours_done': _hours_done(figures),
        'outcome': outcome,
        'people': [{
            'person': person.person,
            'capacity': hours(person.capacity),
            'hours': _or_no_time_source(person.hours_done, hours(person.hours_done)),
            'delta': _or_no_time_source(person.hours_done, hours(person.capacity_exceeded_by)),
        } for person in figures.people],
    }


def _planned_figures(figures: SprintFigures) -> dict[str, Any]:
    return {
        'capacity': _capacity(figures.everyone),
        'ticket_totals': _ticket_totals(figures),
        'people': [{
            'person': person.person,
            'capacity': hours(person.capacity),
            'ticket_capacity': hours(person.ticket_capacity_left),
            'assigned': hours(person.work_left),
        } for person in figures.people],
    }


def _ongoing_figures(figures: SprintFigures) -> dict[str, Any]:
    return {
        'planned': _planned(figures),
        'hours_done': _hours_done(figures),
        'closed': _closed(figures),
        'left': Block(capacity=_capacity(figures.everyone), ticket_totals=_ticket_totals(figures)),
        'people': [{
            'person': person.person,
            'capacity': hours(person.capacity),
            'hours': _or_no_time_source(person.hours_done, hours(person.hours_done)),
            'ticket_capacity_left': hours(person.ticket_capacity_left),
            'assigned_left': hours(person.work_left),
        } for person in figures.people],
    }


def _planned(figures: SprintFigures) -> Block:
    planned = Block(capacity=hours(figures.everyone.capacity), estimate=hours(figures.estimate))
    if figures.reestimated_by:
        planned['reestimated_by'] = hours(figures.reestimated_by)
    return planned


def _hours_done(figures: SprintFigures) -> Block | str:
    if not figures.hours:
        return NO_TIME_SOURCE
    return Block(
        total=hours(figures.hours.total), tickets=hours(figures.hours.tickets), others=hours(figures.hours.others)
    )


def _closed(figures: SprintFigures) -> Block:
    closed = Block(done=_count(figures.outcome.done))
    if figures.outcome.discarded:
        closed['discarded'] = _count(figures.outcome.discarded)
    return closed


def _capacity(everyone: Workload) -> Block:
    # Only a project's shows its non-ticket percent.
    capacity = Block(total_hours=hours(everyone.capacity_left))
    if everyone.project:
        capacity['non_ticket_percent'] = _percent(everyone.non_ticket_percent)
    capacity['for_tickets_hours'] = hours(everyone.ticket_capacity_left)
    return capacity


def _ticket_totals(figures: SprintFigures) -> Block:
    totals = figures.ticket_totals
    block = Block(num=totals.num, points=number(totals.points), estimated_hours=hours(totals.estimated_hours))
    if totals.unassigned_hours:
        block['unassigned_hours'] = hours(totals.unassigned_hours)
    return block


def _ended_ticket(ticket: SprintTicket) -> dict[str, Any]:
    row = {
        'key': ticket.key,
        'status': ticket.status,
        'points': number(ticket.points),
        'estimate': hours(ticket.estimate),
        'hours': _or_no_time_source(ticket.hours, hours(ticket.hours)),
        'delta': _or_no_time_source(ticket.hours, hours(ticket.delta)),
    }
    if ticket.reestimated_by:
        row['reestimated_by'] = hours(ticket.reestimated_by)
    return row


def _planned_ticket(ticket: SprintTicket) -> dict[str, Any]:
    # A planned ticket's estimate is what's left of it.
    return {
        'key': ticket.key,
        'assignee': ticket.assignee,
        'points': number(ticket.points),
        'estimate': hours(ticket.hours_left),
    }


def _ongoing_ticket(ticket: SprintTicket) -> dict[str, Any]:
    row = {
        'key': ticket.key,
        'assignee': ticket.assignee,
        'status': ticket.status,
        'points': number(ticket.points),
        'estimate': hours(ticket.estimate),
        'hours': _or_no_time_source(ticket.hours, hours(ticket.hours)),
        'hours_left': hours(ticket.hours_left),
    }
    if ticket.reestimated_by:
        row['reestimated_by'] = hours(ticket.reestimated_by)
    return row


def _problems(problems: SprintProblems) -> Block:
    # Leaves out empty sections.
    sections: dict[str, list[Any]] = {
        'wont_fit': [_where(workload) | {'by': hours(workload.wont_fit_by)} for workload in problems.wont_fit],
        'spare_capacity': [
            _where(workload) | {'by': hours(workload.spare_capacity_by)} for workload in problems.spare_capacity
        ],
        'capacity_exceeded': [
            _where(workload) | {'hours': hours(workload.hours_done), 'capacity': hours(workload.capacity)}
            for workload in problems.capacity_exceeded
        ],
        'estimate_exceeded': [
            {'key': ticket.key, 'hours': hours(ticket.hours), 'estimate': hours(ticket.estimate)}
            for ticket in problems.estimate_exceeded
        ],
        'unassigned': [ticket.key for ticket in problems.unassigned],
        'no_estimate': [ticket.key for ticket in problems.no_estimate],
        'blocked_in_sprint': [_blocked(blocked) for blocked in problems.blocked_in_sprint],
        'blocked_outside': [_blocked(blocked) for blocked in problems.blocked_outside],
    }
    return Block({name: rows for name, rows in sections.items() if rows})


def _where(workload: Workload) -> dict[str, Any]:
    return {'person': workload.person or 'all', 'project': workload.project or 'all'}


def _blocked(blocked: Blocked) -> Flow:
    return Flow(key=blocked.key, by=list(blocked.by))


def _days_and_hours(value: timedelta) -> str:
    # To the nearest hour, such as 3d 12h.
    days, rest = divmod(round(value / timedelta(hours=1)), 24)
    return f'{days}d {rest}h'


def _count(count: TicketCount) -> dict[str, Any]:
    return {'tickets': count.tickets, 'points': number(count.points)}


def _or_no_time_source(hours_or_none: object, value: CustomValue | int) -> CustomValue | int:
    # The value, or "no time source" when the hours it comes from are None.
    return NO_TIME_SOURCE if hours_or_none is None else value


def _percent(value: float | None) -> int | None:
    return round(value) if value is not None else None


def _speed(value: float | None) -> CustomValue | int:
    return number(round(value, SPEED_DECIMALS)) if value is not None else None
