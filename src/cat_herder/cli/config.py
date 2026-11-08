from collections.abc import Mapping
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from cat_herder.cli.yaml_format import load
from cat_herder.domain.config import (
    DEFAULT_CAPACITY_MARGIN_HOURS,
    Access,
    CommandCredential,
    Config,
    Credential,
    EnvCredential,
    JiraSourceConfig,
    Person,
    Project,
    Repository,
    SourceConfig,
    TicketOrigin,
    TicketSourceConfig,
    TimeOrigin,
    TimeSourceConfig,
    TogglSourceConfig,
)

CONFIG_PATH_ENV = 'CAT_HERDER_CONFIG'
DEFAULT_CONFIG_PATH = Path('~/.config/cat-herder/config.yaml')


class ConfigError(Exception):
    """The config can't be used. The message has one line per problem, each starting with the config's path."""


class WriteNotAllowed(Exception):
    """The config gives the source read-only access."""


def load_config(environ: Mapping[str, str]) -> Config:
    """Read and validate the config at CAT_HERDER_CONFIG, or at the default path, with `~` expanded.

    Paths in it expand `~`, and relative ones are relative to the config's directory.

    Raises:
        ConfigError: if it can't be read, isn't YAML, breaks the schema, or refers to something it doesn't define.
    """
    path = Path(environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH).expanduser()
    try:
        with path.open() as stream:
            document = load(stream)
    except OSError as error:
        raise ConfigError(f'{path}: {error.strerror}') from error
    except yaml.YAMLError as error:
        raise ConfigError(f'{path}: {error}') from error

    # types-jsonschema leaves one parameter of iter_errors' deprecated overload untyped.
    errors = _VALIDATOR.iter_errors(document)  # pyright: ignore[reportUnknownMemberType]
    problems = [f'{error.json_path}: {error.message}' for error in errors]
    if problems:
        raise ConfigError(_report(path, problems))
    config = _build(document, path.parent)
    problems = _reference_problems(config)
    if problems:
        raise ConfigError(_report(path, problems))
    return config


_VALIDATOR = Draft202012Validator(
    yaml.safe_load(files('cat_herder.cli').joinpath('schemas', 'config.schema.yaml').read_text()),
    format_checker=Draft202012Validator.FORMAT_CHECKER,
)


def _report(path: Path, problems: list[str]) -> str:
    return '\n'.join(f'{path}: {problem}' for problem in sorted(problems))


def _build(document: dict[str, Any], directory: Path) -> Config:
    def path(value: str) -> Path:
        return directory / Path(value).expanduser()

    return Config(
        data_dir=path(document['data_dir']),
        sources=tuple(_source(slug, source) for slug, source in document['sources'].items()),
        projects=tuple(_project(slug, project) for slug, project in document['projects'].items()),
        people=tuple(_person(slug, person) for slug, person in document.get('people', {}).items()),
        repositories=tuple(
            Repository(slug=slug, path=path(value)) for slug, value in document.get('repositories', {}).items()
        ),
        default_non_ticket_percent=document.get('default_non_ticket_percent'),
        capacity_margin_hours=document.get('capacity_margin_hours', DEFAULT_CAPACITY_MARGIN_HOURS),
    )


def _source(slug: str, source: dict[str, Any]) -> SourceConfig:
    if source['type'] == 'jira':
        fields = source.get('fields', {})
        return JiraSourceConfig(
            slug=slug,
            access=Access(source['access']),
            fetch_window_seconds=source['fetch_window_seconds'],
            done_statuses=tuple(source['done_statuses']),
            discarded_statuses=tuple(source.get('discarded_statuses', ())),
            blocking_relation=source.get('blocking_relation'),
            url=source['url'],
            points_field=fields.get('points'),
            sprints_field=fields.get('sprints'),
            custom_fields=dict(source.get('custom_fields', {})),
            email=_credential(source['credentials']['email']),
            token=_credential(source['credentials']['token']),
        )
    return TogglSourceConfig(
        slug=slug,
        access=Access(source['access']),
        fetch_window_seconds=source['fetch_window_seconds'],
        workspace=source['workspace'],
        history_from=datetime.fromisoformat(source['history_from']),
        token=_credential(source['credentials']['token']),
    )


def _credential(credential: dict[str, str]) -> Credential:
    if 'env' in credential:
        return EnvCredential(name=credential['env'])
    return CommandCredential(command=credential['command'])


def _project(slug: str, project: dict[str, Any]) -> Project:
    tickets = project.get('tickets')
    time = project.get('time')
    return Project(
        slug=slug,
        tickets=TicketOrigin(source=tickets['source'], space=tickets['space']) if tickets else None,
        time=TimeOrigin(source=time['source'], spaces=tuple(time['spaces'])) if time else None,
        repositories=tuple(project.get('repositories', ())),
    )


def _person(slug: str, person: dict[str, Any]) -> Person:
    capacity = person.get('weekly_capacity', {})
    return Person(
        slug=slug,
        identity_by_source=dict(person['identities']),
        weekly_hours=capacity.get('hours', 0),
        hours_by_project=dict(capacity.get('projects', {})),
    )


def _reference_problems(config: Config) -> list[str]:
    source_by_slug = {source.slug: source for source in config.sources}
    project_slugs = {project.slug for project in config.projects}
    repository_slugs = {repository.slug for repository in config.repositories}
    problems: list[str] = []
    for person in config.people:
        location = f'$.people.{person.slug}'
        problems += [
            f"{location}.identities: '{source}' is not a defined source"
            for source in person.identity_by_source
            if source not in source_by_slug
        ]
        problems += [
            f"{location}.weekly_capacity.projects: '{project}' is not a defined project"
            for project in person.hours_by_project
            if project not in project_slugs
        ]

    project_by_time_space: dict[tuple[str, str], str] = {}
    for project in config.projects:
        location = f'$.projects.{project.slug}'
        if project.tickets and not isinstance(source_by_slug.get(project.tickets.source), TicketSourceConfig):
            problems.append(f"{location}.tickets.source: '{project.tickets.source}' is not a defined ticket source")
        if project.time:
            if not isinstance(source_by_slug.get(project.time.source), TimeSourceConfig):
                problems.append(f"{location}.time.source: '{project.time.source}' is not a defined time source")
            for name in project.time.spaces:
                owner = project_by_time_space.setdefault((project.time.source, name), project.slug)
                if owner != project.slug:
                    problems.append(f"{location}.time.spaces: '{name}' is already in project '{owner}'")
        problems += [
            f"{location}.repositories: '{repository}' is not a defined repository"
            for repository in project.repositories
            if repository not in repository_slugs
        ]
    return problems


def check_writable(config: Config, source: str) -> None:
    """Check the config lets cat-herder write to the source, before contacting it.

    Raises:
        WriteNotAllowed: if the config gives the source read-only access.
    """
    if config.source(source).access is not Access.FULL:
        raise WriteNotAllowed(f'{source} is read-only in the config')
