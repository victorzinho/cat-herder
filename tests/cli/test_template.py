import io

import pytest
from pytest import CaptureFixture, MonkeyPatch

from cat_herder.cli import main
from tests.helpers import resource
from tests.jira_api import JiraApi


@pytest.mark.parametrize(('command', 'expected_yaml'), [
    pytest.param(['template', '--project', 'sat'], 'template-sat.yaml', id='create-every-type'),
    pytest.param(['template', '--project', 'sat', '--type', 'Bug'], 'template-sat-bug.yaml', id='create-one-type'),
    pytest.param(['template', 'SAT-7'], 'template-sat-7.yaml', id='edit'),
])
def test_template_comments_each_field_with_the_values_jira_takes(
    jira_api: JiraApi, capsys: CaptureFixture[str], command: list[str], expected_yaml: str
) -> None:
    # WHEN
    exit_code = main(command)

    # THEN
    assert (exit_code, capsys.readouterr()) == (0, (resource(f'cli/{expected_yaml}').read_text(), ''))


@pytest.mark.parametrize(('command', 'expected_yaml'), [
    pytest.param(['template', '--project', 'sat'], 'template-sat-local-copy.yaml', id='create'),
    pytest.param(['template', 'SAT-7'], 'template-sat-7-local-copy.yaml', id='edit'),
])
def test_template_comments_each_field_with_the_values_in_the_local_copy_when_jira_is_unreachable(
    jira_api: JiraApi, capsys: CaptureFixture[str], command: list[str], expected_yaml: str
) -> None:
    # GIVEN SAT synced, then Jira unreachable
    main(['sync'])
    capsys.readouterr()
    jira_api.reachable = False

    # WHEN
    exit_code = main(command)

    # THEN
    printed = capsys.readouterr()
    assert (exit_code, printed.out) == (0, resource(f'cli/{expected_yaml}').read_text())
    assert printed.err.startswith('jira unreachable, SAT is a local copy from ')


def test_a_filled_in_create_template_creates_the_ticket(
    jira_api: JiraApi, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    # GIVEN the create template for a Task, with a title
    main(['template', '--project', 'sat', '--type', 'Task'])
    filled_in = capsys.readouterr().out.replace("title: ''", 'title: Alert on retries')
    monkeypatch.setattr('sys.stdin', io.StringIO(filled_in))
    jira_api.requests.clear()

    # WHEN
    exit_code = main(['create'])

    # THEN
    assert (exit_code, capsys.readouterr()) == (0, ('SAT-11\n', ''))
    issue_fields = {'project': {'key': 'SAT'}, 'summary': 'Alert on retries', 'issuetype': {'name': 'Task'}}
    assert jira_api.writes() == [('POST', 'issue', {'fields': issue_fields})]


def test_an_unchanged_edit_template_writes_nothing(
    jira_api: JiraApi, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    # GIVEN SAT-7's edit template
    main(['template', 'SAT-7'])
    monkeypatch.setattr('sys.stdin', io.StringIO(capsys.readouterr().out))
    jira_api.requests.clear()

    # WHEN
    exit_code = main(['edit', 'SAT-7'])

    # THEN
    assert (exit_code, capsys.readouterr()) == (0, ('', ''))
    assert jira_api.writes() == []


@pytest.mark.parametrize(('command', 'error'), [
    pytest.param(['template', 'SAT-7', '--type', 'Bug'], '--type is only for --project', id='type-with-key'),
    pytest.param(
        ['template', '--project', 'sat', '--force-fetch'],
        '--force-fetch is only for a key',
        id='force-fetch-with-project',
    ),
    pytest.param(['template', '--project', 'nope'], 'not a configured project: nope', id='unknown-project'),
])
def test_template_rejects_usage_errors_without_requests(
    jira_api: JiraApi, capsys: CaptureFixture[str], command: list[str], error: str
) -> None:
    # WHEN
    exit_code = main(command)

    # THEN
    assert (exit_code, capsys.readouterr().err) == (2, f'cat-herder template: {error}\n')
    assert jira_api.requests == []


def test_template_reports_a_type_the_space_doesnt_have(jira_api: JiraApi, capsys: CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['template', '--project', 'sat', '--type', 'Story'])

    # THEN
    assert (exit_code, capsys.readouterr()) == (1, ('', 'cat-herder: SAT in jira has no type Story, only: Task, Bug\n'))


def test_template_reports_a_ticket_not_in_its_source(jira_api: JiraApi, capsys: CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['template', 'SAT-404'])

    # THEN
    assert (exit_code, capsys.readouterr()) == (1, ('', 'cat-herder: SAT-404 is not in its source\n'))
