from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from pytest import CaptureFixture, MonkeyPatch

from cat_herder.cli import main
from tests.jira_api import JiraApi

RESOURCES = Path(__file__).parents[1] / 'resources' / 'cli'
TICKET_SCHEMA = Draft202012Validator(
    yaml.safe_load(files('cat_herder.cli').joinpath('schemas', 'ticket.schema.yaml').read_text()),
    format_checker=Draft202012Validator.FORMAT_CHECKER,
)


def test_prints_the_ticket_with_its_changes(jira_api: JiraApi, capsys: pytest.CaptureFixture[str]):
    # WHEN
    exit_code = main(['show', 'SAT-7', '--changes'])

    # THEN
    output = capsys.readouterr().out
    assert exit_code == 0
    assert output == (RESOURCES / 'show-sat-7-with-changes.yaml').read_text()
    assert list(TICKET_SCHEMA.iter_errors(yaml.safe_load(output))) == []  # pyright: ignore[reportUnknownMemberType]


def test_brief_leaves_out_comments_and_attachments(jira_api: JiraApi, capsys: CaptureFixture[str]):
    # WHEN
    exit_code = main(['show', 'SAT-7', '--brief'])

    # THEN
    shown = yaml.safe_load(capsys.readouterr().out)
    assert exit_code == 0
    assert {'comments', 'attachments', 'changes'}.isdisjoint(shown)
    assert shown['description'] == 'The import fails **silently** when the provider times out.'


def test_warns_when_answering_from_the_local_copy(jira_api: JiraApi, capsys: CaptureFixture[str]):
    # GIVEN SAT-7 shown once, and Jira unreachable since
    main(['show', 'SAT-7'])
    shown_before = capsys.readouterr().out
    jira_api.reachable = False

    # WHEN
    exit_code = main(['show', 'SAT-7', '--force-fetch'])

    # THEN
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == shown_before
    assert captured.err.startswith('jira unreachable, SAT-7 is a local copy from ')


@pytest.mark.parametrize(('key', 'reachable', 'error'), [
        pytest.param('SAT-9', True, 'cat-herder: SAT-9 is not in its source\n', id='not-in-source'),
        pytest.param('SAT-7', False,'cat-herder: jira unreachable, and SAT-7 has no local copy\n',
                     id='unreachable-no-local-copy'),
        pytest.param('SAT', True, 'cat-herder: SAT is not a ticket key, such as SAT-7\n', id='not-a-key'),
])
def test_fails_with_a_message(jira_api: JiraApi, capsys: CaptureFixture[str], key: str, reachable: bool, error: str):
    # GIVEN
    jira_api.reachable = reachable

    # WHEN
    exit_code = main(['show', key])

    # THEN
    captured = capsys.readouterr()
    assert exit_code == 1
    assert (captured.out, captured.err) == ('', error)


def test_fails_without_credentials(jira_api: JiraApi, capsys: CaptureFixture[str], monkeypatch: MonkeyPatch):
    # GIVEN
    monkeypatch.delenv('JIRA_TOKEN')

    # WHEN
    exit_code = main(['show', 'SAT-7'])

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err == 'cat-herder: jira needs JIRA_TOKEN set\n'
