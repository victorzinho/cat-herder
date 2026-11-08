from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from cat_herder.cli import main
from cat_herder.cli.config import CONFIG_PATH_ENV, ConfigError, load_config
from cat_herder.domain.config import (
    Access,
    CommandCredential,
    Config,
    EnvCredential,
    JiraSourceConfig,
    Person,
    Project,
    Repository,
    TicketOrigin,
    TimeOrigin,
    TogglSourceConfig,
)
from tests.dates import parse
from tests.jira_api import JiraApi

RESOURCES = Path(__file__).parent.parent / 'resources' / 'config'


@pytest.mark.parametrize(('environ', 'expected_path'), [
        pytest.param({CONFIG_PATH_ENV: '~/elsewhere.yaml'}, '~/elsewhere.yaml', id='environment-variable'),
        pytest.param({}, '~/.config/cat-herder/config.yaml', id='default'),
])
def test_load_config_reads_the_config_path(
    environ: dict[str, str], expected_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN an empty home, where no config exists
    monkeypatch.setenv('HOME', str(tmp_path))

    # WHEN
    with pytest.raises(ConfigError) as error_info:
        load_config(environ)

    # THEN
    assert str(error_info.value) == f'{Path(expected_path).expanduser()}: No such file or directory'


def test_load_config_reads_relative_paths_from_the_configs_directory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # GIVEN the config in tmp_path/config, run from elsewhere
    (tmp_path / 'config').mkdir()
    (tmp_path / 'elsewhere').mkdir()
    monkeypatch.chdir(tmp_path / 'elsewhere')
    config_path = tmp_path / 'config' / 'config.yaml'
    cli_config = (Path(__file__).parents[1] / 'resources' / 'cli' / 'config.yaml').read_text()
    config_path.write_text(f'{cli_config}repositories:\n  sat: ../sat\n')

    # WHEN
    config = load_config({CONFIG_PATH_ENV: str(config_path)})

    # THEN
    assert config.data_dir.resolve() == tmp_path / 'config' / 'data'
    assert config.repositories[0].path.resolve() == tmp_path / 'sat'


def test_load_config_builds_every_option() -> None:
    # WHEN
    config = load_config({CONFIG_PATH_ENV: str(RESOURCES / 'every-option.yaml')})

    # THEN
    assert config == Config(
        data_dir=Path.home() / 'cat-herder-data',
        default_non_ticket_percent=20,
        capacity_margin_hours=5,
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
                email=EnvCredential(name='JIRA_EMAIL'),
                token=CommandCredential(command='pass show jira/token'),
            ),
            TogglSourceConfig(
                slug='toggl',
                access=Access.READ_ONLY,
                fetch_window_seconds=900,
                workspace=123,
                history_from=parse('2026-01-01T00:00:00+01:00'),
                token=EnvCredential(name='TOGGL_TOKEN'),
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
                slug='admin', tickets=None, time=TimeOrigin(source='toggl', spaces=('Admin',))
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
                "$.sources.toggl.credentials.token: {'env': 'TOGGL_TOKEN', 'command': 'pass show toggl/token'} is not "
                'valid under any of the given schemas',
                "$.sources.toggl.history_from: '2026-01-01' is not a 'date-time'",
            ],
            id='errors inside sources',
        ),
        pytest.param(
            'undefined-references.yaml',
            [
                "$.people.ana.identities: 'gitlab' is not a defined source",
                "$.people.ana.weekly_capacity.projects: 'nope' is not a defined project",
                "$.projects.admin.time.spaces: 'Shared' is already in project 'web'",
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
        load_config({CONFIG_PATH_ENV: str(path)})

    # THEN
    assert str(error_info.value).splitlines() == [f'{path}: {problem}' for problem in problems]


@pytest.mark.parametrize('command', [
    pytest.param(['create', 'sat-7.yaml'], id='create'),
    pytest.param(['edit', 'SAT-7', 'sat-7.yaml'], id='edit'),
    pytest.param(['comment', 'SAT-7', 'Done'], id='comment'),
])
def test_writes_contact_no_source_that_the_config_makes_read_only(
    jira_api: JiraApi, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], command: list[str]
) -> None:
    # GIVEN Jira read-only in the config
    config = tmp_path / 'config.yaml'
    cli_config = Path(__file__).parents[1] / 'resources' / 'cli' / 'config.yaml'
    config.write_text(cli_config.read_text().replace('access: full', 'access: read-only'))
    monkeypatch.setenv('CAT_HERDER_CONFIG', str(config))
    (tmp_path / 'sat-7.yaml').write_text('project: sat\ntype: Task\ntitle: Retry meteo imports\n')

    # WHEN
    exit_code = main(command)

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err == 'cat-herder: jira is read-only in the config\n'
    assert jira_api.requests == []
