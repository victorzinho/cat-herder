import io
from pathlib import Path

import pytest
import yaml
from pytest import CaptureFixture, MonkeyPatch

from cat_herder.cli import main
from tests.jira_api import JiraApi


def test_edit_writes_only_the_fields_that_differ_from_the_ticket(
    jira_api: JiraApi, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    # GIVEN SAT-7 as show prints it, with a new title, size and sprints
    main(['show', 'SAT-7'])
    document = yaml.safe_load(capsys.readouterr().out)
    document |= {'title': 'Retry meteo imports', 'custom_fields': {'size': '🕯️'}, 'sprints': ['All Sprint 1']}
    edited = tmp_path / 'sat-7.yaml'
    edited.write_text(yaml.safe_dump(document, allow_unicode=True))
    jira_api.requests.clear()

    # WHEN
    exit_code = main(['edit', 'SAT-7', str(edited)])

    # THEN
    assert (exit_code, capsys.readouterr()) == (0, ('', ''))
    assert jira_api.writes() == [('PUT', 'issue/SAT-7', {
        'fields': { 'summary': 'Retry meteo imports', 'customfield_10043': {'value': '🕯️'}, 'customfield_10020': None },
        'update': {},
    })]


def test_edit_reads_a_partial_ticket_from_stdin(jira_api: JiraApi, monkeypatch: MonkeyPatch) -> None:
    # GIVEN
    ticket_yaml = 'status: Done\nlabels: [backend, meteo]\nlinks: [{from: SAT-7, relation: blocks, to: SAT-9}]\n'
    monkeypatch.setattr('sys.stdin', io.StringIO(ticket_yaml))

    # WHEN
    exit_code = main(['edit', 'SAT-7'])

    # THEN
    assert exit_code == 0
    assert jira_api.writes() == [
        ('PUT', 'issue/SAT-7', {'fields': {'labels': ['backend', 'meteo']}, 'update': {}}),
        ('DELETE', 'issueLink/10062', None),
        ('POST', 'issue/SAT-7/transitions', {'transition': {'id': '31'}}),
    ]


def test_edit_keeps_the_ticket_as_refreshed_when_the_write_fails_partway(
    jira_api: JiraApi, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    # GIVEN Jira rejecting new links
    jira_api.rejecting.add('POST issueLink')
    edited = tmp_path / 'sat-7.yaml'
    edited.write_text('title: Retry meteo imports\nlinks: [{from: SAT-7, relation: blocks, to: SAT-10}]\n')

    # WHEN
    exit_code = main(['edit', 'SAT-7', str(edited)])

    # THEN the error says what was written, and the ticket is stored within the window
    assert exit_code == 1
    assert capsys.readouterr().err.startswith('cat-herder: SAT-7 got title, and not link SAT-7 blocks SAT-10')
    jira_api.requests.clear()
    main(['show', 'SAT-7'])
    assert jira_api.requests == []


@pytest.mark.parametrize(('ticket_yaml', 'error'), [
    pytest.param('title: 5\n', "$.title: 5 is not of type 'string'", id='schema'),
    pytest.param(
        'key: SAT-7\ncreated: 2026-01-01T00:00:00Z\nspent_hours: 1\nparent: {key: SAT-2, title: Other}\n',
        'SAT-7 has read-only fields that differ: created, parent.title',
        id='read-only',
    ),
    pytest.param('project: web\n', 'SAT-7 has read-only fields that differ: project', id='project'),
    pytest.param('assignee: bob\n', 'bob is not in people', id='person'),
    pytest.param('sprints: [All Sprint 9]\n', 'no sprint All Sprint 9 in the local copy', id='sprint'),
    pytest.param('custom_fields: {colour: red}\n', 'custom fields not in the config: colour', id='custom-field'),
    pytest.param("links: [{relation: blocks, to: SAT-9}]\n", 'links need from and to when editing', id='link-end'),
])
def test_edit_writes_nothing_for_a_ticket_yaml_it_cant_use(
    jira_api: JiraApi, tmp_path: Path, capsys: CaptureFixture[str], ticket_yaml: str, error: str
) -> None:
    # GIVEN
    edited = tmp_path / 'sat-7.yaml'
    edited.write_text(ticket_yaml)

    # WHEN
    exit_code = main(['edit', 'SAT-7', str(edited)])

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err.startswith(f'cat-herder: {error}')
    assert jira_api.writes() == []


def test_edit_reports_a_ticket_not_in_its_source(jira_api: JiraApi, tmp_path: Path, capsys: CaptureFixture[str]):
    # GIVEN
    edited = tmp_path / 'sat-9.yaml'
    edited.write_text('title: Gone\n')

    # WHEN
    exit_code = main(['edit', 'SAT-9', str(edited)])

    # THEN
    assert (exit_code, capsys.readouterr().err) == (1, 'cat-herder: SAT-9 is not in its source\n')
    assert jira_api.writes() == []
