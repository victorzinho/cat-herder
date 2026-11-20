import argparse
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from cat_herder.cli.validation import unknown_projects
from cat_herder.domain.config import Config
from cat_herder.services.tickets_service import TicketsService
from cat_herder.sources.factory import build_ticket_sources
from cat_herder.store.database import database_session, open_database
from cat_herder.store.git_repositories import current_git_repository

if TYPE_CHECKING:
    from cat_herder.services.search_service import SearchHit


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('query', nargs='+', help='words to find, or what the ticket is about, in English')
    parser.add_argument('--project', action='append', default=[], help='a project slug; repeat for any of several')
    parser.add_argument('--status', action='append', default=[], help="a status's name; repeat for any of several")
    parser.add_argument('--limit', type=_positive, default=10, help='how many tickets to show at most (default 10)')
    parser.add_argument('--force-fetch', action='store_true', help="fetch even within the source's window")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Print the tickets best matching the query, after syncing their projects.

    Each ticket is a line with its key, status and title, in columns, and an indented one with the part of it that best
    matches, if any. In a terminal, lines are cut to its width.

    Returns:
        The exit code: 2 for a project the config doesn't have, as for other usage errors.
    """
    if unknown := unknown_projects(config, args.project):
        print(f'cat-herder search: not configured projects: {", ".join(unknown)}', file=sys.stderr)
        return 2
    sources = build_ticket_sources(config, environ)
    with database_session(open_database(config.data_dir)) as session:
        tickets_service = TicketsService(config, session, sources, current_git_repository(config, cwd))
        hits = tickets_service.search(' '.join(args.query), args.project, args.status, args.limit, args.force_fetch)
    _print_hits(hits, shutil.get_terminal_size().columns if sys.stdout.isatty() else None)
    return 0


def _print_hits(hits: Sequence['SearchHit'], width: int | None) -> None:
    # width is the terminal's, or None to print lines whole.
    key_width = max((len(hit.ticket.key) for hit in hits), default=0)
    status_width = max((len(hit.ticket.status) for hit in hits), default=0)
    for hit in hits:
        ticket = hit.ticket
        print(_cut(f'{ticket.key:<{key_width}}  {ticket.status:<{status_width}}  {ticket.title}', width))
        if hit.snippet:
            print(_cut(f'{"":<{key_width}}  {hit.snippet}', width))


def _cut(line: str, width: int | None) -> str:
    return line if width is None or len(line) <= width else f'{line[:width - 1]}…'


def _positive(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f'{value} is not a positive whole number')
    return int(value)
