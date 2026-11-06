from datetime import date
from pathlib import Path

import pytest

from cat_herder.cli.config import DEFAULT_CONFIG_PATH, ConfigError, find_config, load_config
from cat_herder.domain.config import (
    Access,
    Config,
    JiraSourceConfig,
    Person,
    Project,
    Repository,
    TicketOrigin,
    TimeOrigin,
    TogglSourceConfig,
)

RESOURCES = Path(__file__).parent.parent / 'resources' / 'config'


def test_find_config_uses_the_environment_variable() -> None:
    # WHEN / THEN
    assert find_config({'CAT_HERDER_CONFIG': '~/elsewhere.yaml'}) == Path.home() / 'elsewhere.yaml'


def test_find_config_defaults_to_the_user_config_directory() -> None:
    # WHEN / THEN
    assert find_config({}) == DEFAULT_CONFIG_PATH.expanduser()


def test_load_config_builds_every_option() -> None:
    # WHEN
    config = load_config(RESOURCES / 'every-option.yaml')

    # THEN
    assert config == Config(
        data_dir=Path.home() / 'cat-herder-data',
        default_non_ticket_percent=20,
        sources=(
            JiraSourceConfig(
                slug='jira',
                access=Access.FULL,
                fetch_window_seconds=60,
                done_statuses=('Done',),
                discarded_statuses=('Cancelled',),
                blocking_relation='blocks',
                url='https://example.atlassian.net',
                points_field='customfield_10035',
                sprints_field='customfield_10020',
                custom_fields={'size': 'customfield_10043'},
                email_env='JIRA_EMAIL',
                token_env='JIRA_TOKEN',
            ),
            TogglSourceConfig(
                slug='toggl',
                access=Access.READ_ONLY,
                fetch_window_seconds=900,
                workspace=123,
                history_from=date(2026, 1, 1),
                token_env='TOGGL_TOKEN',
            ),
        ),
        people=(
            Person(
                slug='ana',
                identity_by_source={'jira': 'abc123', 'toggl': 456},
                weekly_hours=30,
                hours_by_project={'sat': 8},
            ),
        ),
        repositories=(Repository(slug='sat', path=Path('/code/sat')),),
        projects=(
            Project(
                slug='sat',
                tickets=TicketOrigin(source='jira', space='SAT'),
                time=TimeOrigin(source='toggl', spaces=('SAT-2025', 'SAT-2026')),
                repositories=('sat',),
            ),
            Project(
                slug='comercial', tickets=None, time=TimeOrigin(source='toggl', spaces=('Comercial',))
            ),
        ),
    )


@pytest.mark.parametrize(
    ('filename', 'problems'),
    [
        pytest.param('missing.yaml', ['No such file or directory'], id='missing file'),
        pytest.param(
            'schema-errors.yaml',
            ["$.projects.sat.tickets: 'space' is a required property", "$: 'data_dir' is a required property"],
            id='schema errors',
        ),
        pytest.param(
            'source-errors.yaml',
            [
                "$.sources.jira: Additional properties are not allowed ('fieldz' was unexpected)",
                "$.sources.toggl.history_from: '2026-13-01' is not a 'date'",
            ],
            id='errors inside sources',
        ),
        pytest.param(
            'undefined-references.yaml',
            [
                "$.people.ana.identities: 'gitlab' is not a defined source",
                "$.people.ana.weekly_capacity.projects: 'nope' is not a defined project",
                "$.projects.comercial.time.spaces: 'Shared' is already in project 'web'",
                "$.projects.sat.repositories: 'sat-meteo' is not a defined repository",
                "$.projects.sat.tickets.source: 'toggl' is not a defined ticket source",
                "$.projects.sat.time.source: 'jira' is not a defined time source",
                "$.projects.web.tickets.source: 'jirra' is not a defined ticket source",
            ],
            id='undefined references',
        ),
    ],
)
def test_load_config_lists_every_problem(filename: str, problems: list[str]) -> None:
    # GIVEN
    path = RESOURCES / filename

    # WHEN
    with pytest.raises(ConfigError) as error_info:
        load_config(path)

    # THEN
    assert str(error_info.value).splitlines() == [f'{path}: {problem}' for problem in problems]
