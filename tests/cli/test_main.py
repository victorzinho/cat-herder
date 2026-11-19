from importlib.metadata import version
from pathlib import Path

import pytest

from cat_herder.cli import main
from tests.helpers import resource
from tests.jira_api import JiraApi


def test_version_prints_the_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    with pytest.raises(SystemExit) as exit_info:
        main(['--version'])

    # THEN
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f'cat-herder {version("cat-herder")}\n'


def test_no_command_prints_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main([])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out.startswith('usage: cat-herder')


def test_an_error_in_what_it_was_given_prints_its_message(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['comment', 'nope:SAT-7', 'A comment'])

    # THEN
    assert (exit_code, capsys.readouterr().err) == (1, 'cat-herder: nope is not a configured ticket source\n')


def test_any_other_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a bug
    def broken(*_: object) -> None:
        raise KeyError('bug')

    monkeypatch.setattr('cat_herder.cli.load_config', broken)

    # WHEN / THEN
    with pytest.raises(KeyError, match='bug'):
        main(['sync'])


@pytest.mark.parametrize('command', [
    pytest.param(['create', str(resource('cli/ticket-sat.yaml'))], id='create'),
    pytest.param(['create', '--dry-run', str(resource('cli/ticket-sat.yaml'))], id='create-dry-run'),
    pytest.param(['edit', 'SAT-7', str(resource('cli/ticket-sat.yaml'))], id='edit'),
    pytest.param(['edit', '--dry-run', 'SAT-7', str(resource('cli/ticket-sat.yaml'))], id='edit-dry-run'),
    pytest.param(['comment', 'SAT-7', 'Done'], id='comment'),
    pytest.param(['template', '--project', 'sat'], id='create-template'),
    pytest.param(['template', 'SAT-7'], id='edit-template'),
])
def test_writes_to_read_only_make_no_requests(
    jira_api: JiraApi, tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    # GIVEN Jira read-only in the config
    config = tmp_path / 'config.yaml'
    config.write_text(config.read_text().replace('access: full', 'access: read-only'))

    # WHEN
    exit_code = main(command)

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err == 'cat-herder: jira is read-only in the config\n'
    assert jira_api.requests == []
