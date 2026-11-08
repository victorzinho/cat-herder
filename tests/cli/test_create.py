import io
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from cat_herder.cli import main
from tests.jira_api import JiraApi


def test_create_prints_the_new_tickets_key(jira_api: JiraApi, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]):
    # GIVEN a ticket with a link whose missing end stands for it
    ticket_yaml = 'project: sat\ntype: Task\ntitle: Alert on retries\nlinks: [{relation: blocks, to: SAT-9}]\n'
    monkeypatch.setattr('sys.stdin', io.StringIO(ticket_yaml))

    # WHEN
    exit_code = main(['create'])

    # THEN
    assert (exit_code, capsys.readouterr()) == (0, ('SAT-11\n', ''))
    assert [write[:2] for write in jira_api.writes()] == [('POST', 'issue'), ('POST', 'issueLink')]


@pytest.mark.parametrize(('ticket_yaml', 'error'), [
    pytest.param('type: Task\ntitle: Alert\n', 'project is required to create a ticket', id='no-project'),
    pytest.param('project: web\ntype: Task\ntitle: Alert\n', 'web is not in projects', id='unknown-project'),
    pytest.param(
        'project: sat\ntype: Task\ntitle: Alert\nkey: SAT-1\nparent: {key: SAT-2, status: To do}\n',
        "read-only fields can't be set when creating: key, parent.status",
        id='read-only',
    ),
    pytest.param('project: sat\ntype: Task\ntitle: Alert\nassignee: bob\n', 'bob is not in people', id='person'),
])
def test_create_creates_nothing_for_a_ticket_yaml_it_cant_use(
    jira_api: JiraApi, tmp_path: Path, capsys: CaptureFixture[str], ticket_yaml: str, error: str
) -> None:
    # GIVEN
    new = tmp_path / 'new.yaml'
    new.write_text(ticket_yaml)

    # WHEN
    exit_code = main(['create', str(new)])

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err == f'cat-herder: {error}\n'
    assert jira_api.writes() == []
