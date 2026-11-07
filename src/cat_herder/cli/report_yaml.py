from cat_herder.cli.yaml_output import NO_TIME_SOURCE, Block, dump, hours, number
from cat_herder.domain.report import ProjectReport
from cat_herder.domain.ticket import CustomValue

SPEED_DECIMALS = 2


def project_report_to_yaml(report: ProjectReport) -> str:
    """The report in the shape the docs show, with "no time source" for hours and speeds the project can't have."""
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


def _percent(value: float | None) -> int | None:
    return round(value) if value is not None else None


def _speed(value: float | None) -> CustomValue | int:
    return number(round(value, SPEED_DECIMALS)) if value is not None else None
