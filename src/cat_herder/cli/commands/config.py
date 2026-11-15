import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from cat_herder.domain.config import Config, ConfigPart
from cat_herder.store.config_file import config_to_yaml
from cat_herder.store.git_repositories import current_git_repository


def configure(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(title='actions', dest='action', required=True)
    show = actions.add_parser(
        'show',
        help='show the config',
        description=(
            'Show the config as YAML, with its defaults and absolute paths. Given a path, show only the projects whose '
            'repositories hold it; given a project, only that project. Either way, with their repositories, and their '
            'sources cut to type and access.'
        ),
    )
    show.add_argument(
        'path_or_project',
        nargs='?',
        help="a path in a configured repository or its worktrees, or else a project's slug",
    )
    show.set_defaults(run=run_show)


def run_show(args: argparse.Namespace, config: Config, _environ: Mapping[str, str], cwd: Path) -> int:
    """Print the config, or the part of it for a path or a project.

    Returns:
        The exit code: 2 for an existing path outside the configured repositories, or for something that is neither a
        path nor a project, as for other usage errors.
    """
    target: str | None = args.path_or_project
    part: Config | ConfigPart
    if target is None:
        part = config
    elif (cwd / target).exists():
        if not (repository := current_git_repository(config, cwd / target)):
            return _usage_error(f'{target} is not in a configured repository')
        part = config.for_repository(repository)
    elif target in {project.slug for project in config.projects}:
        part = config.for_project(target)
    else:
        return _usage_error(f'{target} is neither a path nor a project')
    print(config_to_yaml(part), end='')
    return 0


def _usage_error(problem: str) -> int:
    print(f'cat-herder config show: {problem}', file=sys.stderr)
    return 2
