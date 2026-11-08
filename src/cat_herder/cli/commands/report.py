import argparse
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path

from cat_herder.cli.local_copy import sync_local_copy
from cat_herder.cli.report_yaml import ended_sprint_report_to_yaml, project_report_to_yaml
from cat_herder.domain.config import Config
from cat_herder.domain.ticket import Sprint, SprintState
from cat_herder.services.reports_service import ReportsService
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database


def configure(parser: argparse.ArgumentParser) -> None:
    reports = parser.add_subparsers(title='reports', dest='report', required=True)
    project = reports.add_parser(
        'project',
        help="a project's points, hours and speed",
        description="Report a project's done points, its hours on tickets and the rest, and its speed.",
    )
    project.add_argument('project', help="the project's slug")
    project.add_argument('--from', dest='from_date', type=date.fromisoformat, help='the first day, an ISO date')
    project.add_argument('--to', dest='to_date', type=date.fromisoformat, help='the last day, an ISO date')
    project.add_argument('--force-fetch', action='store_true', help="fetch even within the source's window")
    project.set_defaults(run=run_project)

    sprint = reports.add_parser(
        'sprint',
        help="a sprint's plan, hours and outcome",
        description="Report a sprint's plan, hours and outcome per project and in total. Only ended sprints, for now.",
    )
    sprint.add_argument('sprint', help="the sprint's name, or jira:<name> to name its source")
    sprint.add_argument('--force-fetch', action='store_true', help="fetch even within the source's window")
    sprint.set_defaults(run=run_sprint)


def run_project(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Print the project report, after syncing the project's tickets and time entries.

    Returns:
        The exit code: 2 for a project the config doesn't have, or --from after --to, as for other usage errors.
    """
    if problem := _project_usage_problem(args, config):
        print(f'cat-herder report project: {problem}', file=sys.stderr)
        return 2
    with database_session(open_database(config.data_dir)) as session:
        sync_local_copy(config, session, environ, args.force_fetch, [args.project])
        report = ReportsService(config, session).project_report(
            args.project,
            start=_midnight(args.from_date) if args.from_date else None,
            end=_midnight(args.to_date + timedelta(days=1)) if args.to_date else None,
        )
    print(project_report_to_yaml(report), end='')
    return 0


def run_sprint(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Print the report on the sprint, after syncing every project.

    Returns:
        The exit code: 1 if no sprint, or several, have that name, or it hasn't ended.
    """
    source, separator, name = args.sprint.partition(':')
    if not separator or source not in config.ticket_sources():
        source, name = None, args.sprint
    with database_session(open_database(config.data_dir)) as session:
        sync_local_copy(config, session, environ, args.force_fetch)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), None)
        sprints = tickets_service.find_sprints(name, source)
        if problem := _sprint_problem(name, sprints):
            print(f'cat-herder report sprint: {problem}', file=sys.stderr)
            return 1
        report = ReportsService(config, session).ended_sprint_report(sprints[0])
    print(ended_sprint_report_to_yaml(report), end='')
    return 0


def _project_usage_problem(args: argparse.Namespace, config: Config) -> str | None:
    if args.project not in {project.slug for project in config.projects}:
        return f'not a configured project: {args.project}'
    if args.from_date and args.to_date and args.from_date > args.to_date:
        return f'--from {args.from_date} is after --to {args.to_date}'
    return None


def _sprint_problem(name: str, sprints: Sequence[Sprint]) -> str | None:
    if not sprints:
        return f'no sprint is called {name}'
    if len(sprints) > 1:
        return f'{name} is in several sources, use one of: {", ".join(f"{sprint.source}:{name}" for sprint in sprints)}'
    if sprints[0].state != SprintState.ENDED:
        return f'{name} has not ended'
    return None


def _midnight(day: date) -> datetime:
    # In the machine's time zone, as the dates people give are.
    return datetime.combine(day, time()).astimezone()
