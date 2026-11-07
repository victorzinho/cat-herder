from pathlib import Path

import pytest

from cat_herder.cli import main

RESOURCES = Path(__file__).parents[1] / 'resources' / 'cli'


def test_list_prints_the_matching_tickets(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['list', '--project', 'sat'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == (RESOURCES / 'list-sat.yaml').read_text()


@pytest.mark.parametrize(('args', 'error'), [
    pytest.param([], 'give at least one filter', id='no-filter'),
    pytest.param(['--project', 'sat', '--project', 'web'], 'not configured projects: web', id='unknown-project'),
    pytest.param(['--assignee', 'bob'], 'not a configured person: bob', id='unknown-person'),
])
def test_list_rejects_wrong_filters(capsys: pytest.CaptureFixture[str], args: list[str], error: str):
    # WHEN
    exit_code = main(['list', *args])

    # THEN
    assert exit_code == 2
    assert capsys.readouterr().err == f'cat-herder list: {error}\n'
