import argparse
import sys
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path

from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.cli.report_yaml import project_report_to_yaml
from cat_herder.domain.config import Config
from cat_herder.services.reports_service import ReportsService
from cat_herder.services.tickets_service import TicketsService
from cat_herder.services.time_entries_service import TimeEntriesService
from cat_herder.sources.factory import build_ticket_sources, build_time_sources
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


def run_project(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Print the project report, after syncing the project's tickets and time entries.

    Returns:
        The exit code: 2 for a project the config doesn't have, or --from after --to, as for other usage errors.
    """
    if problem := _project_usage_problem(args, config):
        print(f'cat-herder report project: {problem}', file=sys.stderr)
        return 2
    projects = [args.project]
    with database_session(open_database(config.data_dir)) as session:
        git_repo = current_git_repository(config, cwd)
        tickets_service = TicketsService(config, session, build_ticket_sources(config, environ), git_repo)
        time_entries_service = TimeEntriesService(config, session, build_time_sources(config, environ))
        tickets_service.sync(args.force_fetch, projects)
        time_entries_service.sync(args.force_fetch, projects)
        report = ReportsService(config, session).project_report(
            args.project,
            start=_midnight(args.from_date) if args.from_date else None,
            end=_midnight(args.to_date + timedelta(days=1)) if args.to_date else None,
        )
    print(project_report_to_yaml(report), end='')
    return 0


def _project_usage_problem(args: argparse.Namespace, config: Config) -> str | None:
    if args.project not in {project.slug for project in config.projects}:
        return f'not a configured project: {args.project}'
    if args.from_date and args.to_date and args.from_date > args.to_date:
        return f'--from {args.from_date} is after --to {args.to_date}'
    return None


def _midnight(day: date) -> datetime:
    # Local, as the dates people give are.
    return datetime.combine(day, time()).astimezone()
