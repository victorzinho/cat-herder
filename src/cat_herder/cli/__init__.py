import argparse
import logging
import os
import sys
from importlib.metadata import version
from pathlib import Path

from cat_herder.cli.commands import comment, create, edit, report, show, sync
from cat_herder.cli.commands import list as list_command
from cat_herder.cli.config import load_config


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
    comment.configure(commands.add_parser(
        'comment', help='add a comment to a ticket', description='Add a comment, in markdown, to a ticket.'
    ))
    create.configure(commands.add_parser(
        'create',
        help='create a ticket from YAML',
        description='Create a ticket from YAML in the shape show prints, and print its key.',
    ))
    edit.configure(commands.add_parser(
        'edit',
        help='edit a ticket from YAML',
        description='Edit a ticket from YAML in the shape show prints, writing only the fields that differ.',
    ))
    list_command.configure(commands.add_parser(
        'list',
        help='list tickets matching filters',
        description='List the tickets matching every filter, sorted by key, after syncing their projects.',
    ))
    report.configure(commands.add_parser(
        'report', help='report on a project or a sprint', description='Report on a project or a sprint, as YAML.'
    ))
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
    except Exception as error:
        print(f'cat-herder: {error}', file=sys.stderr)
        return 1
    finally:
        logging.getLogger('cat_herder').removeHandler(warnings)
