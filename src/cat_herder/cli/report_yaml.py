from typing import Any

from cat_herder.cli.yaml_output import NO_TIME_SOURCE, Block, dump, hours, number, timestamp
from cat_herder.domain.ticket import CustomValue
from cat_herder.services.reports_types import (
    EndedSprintReport,
    ProjectReport,
    SprintFigures,
    SprintPerson,
    SprintProject,
    SprintTicket,
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
        'projects': [_sprint_project(project) for project in report.projects],
        'total': Block(_sprint_figures(report.total)),
    }))


def _sprint_project(project: SprintProject) -> Block:
    return Block({
        'project': project.project,
        **_sprint_figures(project),
        'tickets': [_ticket(ticket) for ticket in project.tickets],
    })


def _sprint_figures(figures: SprintFigures) -> dict[str, Any]:
    planned = Block(capacity=hours(figures.capacity), estimate=hours(figures.estimate))
    if figures.reestimated_by:
        planned['reestimated_by'] = hours(figures.reestimated_by)
    outcome = Block(done=_count(figures.outcome.done))
    if figures.outcome.discarded:
        outcome['discarded'] = _count(figures.outcome.discarded)
    outcome |= {
        'open': _count(figures.outcome.open),
        'ticket_speed': _or_no_time_source(figures.hours, _speed(figures.ticket_speed)),
        'total_speed': _or_no_time_source(figures.hours, _speed(figures.total_speed)),
        'hours_vs_capacity': _or_no_time_source(figures.hours, hours(figures.hours_vs_capacity)),
    }
    hours_done = Block(
        total=hours(figures.hours.total), tickets=hours(figures.hours.tickets), others=hours(figures.hours.others)
    ) if figures.hours else NO_TIME_SOURCE
    return {
        'planned': planned,
        'hours_done': hours_done,
        'outcome': outcome,
        'people': [_person(person) for person in figures.people],
    }


def _count(count: TicketCount) -> dict[str, Any]:
    return {'tickets': count.tickets, 'points': number(count.points)}


def _person(person: SprintPerson) -> dict[str, Any]:
    return {
        'person': person.person,
        'capacity': hours(person.capacity),
        'hours': _or_no_time_source(person.hours, hours(person.hours)),
        'delta': _or_no_time_source(person.hours, hours(person.delta)),
    }


def _ticket(ticket: SprintTicket) -> dict[str, Any]:
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


def _or_no_time_source(hours_or_none: object, value: CustomValue | int) -> CustomValue | int:
    # The value, or "no time source" when the hours it comes from are None.
    return NO_TIME_SOURCE if hours_or_none is None else value


def _percent(value: float | None) -> int | None:
    return round(value) if value is not None else None


def _speed(value: float | None) -> CustomValue | int:
    return number(round(value, SPEED_DECIMALS)) if value is not None else None
