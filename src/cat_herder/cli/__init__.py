import argparse
import logging
import os
import sys
from importlib.metadata import version
from pathlib import Path

from cat_herder.cli.commands import show, sync
from cat_herder.cli.config import ConfigError, load_config
from cat_herder.services.tickets_service import KeyNotResolved
from cat_herder.sources.errors import CredentialsMissing, SourceError, SourceUnreachable


def main(argv: list[str] | None = None) -> int:
    """Run the cat-herder command line; argv defaults to sys.argv. Warnings and errors go to stderr.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(
        prog='cat-herder', description='Tickets and hours from separate tools, such as Jira and Toggl, in one place.'
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {version("cat-herder")}')
    commands = parser.add_subparsers(title='commands', dest='command')
    show.configure(commands.add_parser('show', help='show one ticket', description='Show one ticket as YAML.'))
    sync.configure(commands.add_parser(
        'sync',
        help='bring the configured spaces into the local copy',
        description='Bring the configured spaces into the local copy, fetching what changed since the last sync.',
    ))
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    warnings = logging.StreamHandler(sys.stderr)
    warnings.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger('cat_herder').addHandler(warnings)
    try:
        config = load_config(os.environ)
        return args.run(args, config, os.environ, Path.cwd())
    except (ConfigError, CredentialsMissing, KeyNotResolved, SourceError, SourceUnreachable) as error:
        print(f'cat-herder: {error}', file=sys.stderr)
        return 1
    finally:
        logging.getLogger('cat_herder').removeHandler(warnings)
