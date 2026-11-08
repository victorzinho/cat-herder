from pathlib import Path

import pytest

from cat_herder.cli import main

RESOURCES = Path(__file__).parents[1] / 'resources' / 'cli'


@pytest.mark.parametrize(('args', 'error'), [
    pytest.param(['web'], 'not a configured project: web', id='unknown-project'),
    pytest.param(
        ['sat', '--from', '2026-10-02', '--to', '2026-10-01'], '--from 2026-10-02 is after --to 2026-10-01', id='range'
    ),
])
def test_report_project_rejects_wrong_arguments(capsys: pytest.CaptureFixture[str], args: list[str], error: str):
    # WHEN
    exit_code = main(['report', 'project', *args])

    # THEN
    assert exit_code == 2
    assert capsys.readouterr().err == f'cat-herder report project: {error}\n'


def test_report_project_prints_the_report_for_the_days_given(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN SAT-10 was done on the 15th, and the 20th to the 22nd have 3.5 h on SAT-7 and 1 h on no ticket
    exit_code = main(['report', 'project', 'sat', '--from', '2026-10-15', '--to', '2026-10-22'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == (RESOURCES / 'report-project-sat.yaml').read_text()


def test_report_sprint_prints_an_ended_sprint(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['report', 'sprint', 'jira:All Sprint 1'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == (RESOURCES / 'report-sprint-all-sprint-1.yaml').read_text()


@pytest.mark.parametrize(('sprint', 'error'), [
    pytest.param('All Sprint 2', 'cat-herder report sprint: All Sprint 2 has not ended', id='not-ended'),
    pytest.param('Sprint 9', 'cat-herder report sprint: no sprint is called Sprint 9', id='unknown'),
])
def test_report_sprint_fails_for_a_sprint_it_cant_report(capsys: pytest.CaptureFixture[str], sprint: str, error: str):
    # WHEN
    exit_code = main(['report', 'sprint', sprint])

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err == f'{error}\n'
