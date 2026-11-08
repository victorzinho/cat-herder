from pathlib import Path

import pytest
from time_machine import TimeMachineFixture

from cat_herder.cli import main
from cat_herder.store.database import database_session, open_database
from cat_herder.store.sprint_repository import SprintRepository
from tests.dates import parse
from tests.factories import new_sprint

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


def test_report_sprint_lists_the_sprints_a_name_stands_for_by_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # GIVEN another All Sprint 1 in jira, from another board
    with database_session(open_database(tmp_path / 'data')) as session:
        SprintRepository(session).save(new_sprint(id='99', name='All Sprint 1'))

    # WHEN
    exit_code = main(['report', 'sprint', 'All Sprint 1'])

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err == (
        'cat-herder report sprint: All Sprint 1 is several sprints, use one of: '
        '--id jira:42, --id jira:99\n'
    )


def test_report_sprint_finds_the_sprint_by_id(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['report', 'sprint', '--id', 'jira:42'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == (RESOURCES / 'report-sprint-all-sprint-1.yaml').read_text()


def test_report_sprint_prints_a_sprint_that_hasnt_started(
    capsys: pytest.CaptureFixture[str], time_machine: TimeMachineFixture
) -> None:
    # GIVEN All Sprint 3 holds SAT-8, with no assignee or estimate
    time_machine.move_to(parse('2026-11-10T12:00:00Z'), tick=False)

    # WHEN
    exit_code = main(['report', 'sprint', 'All Sprint 3'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == (RESOURCES / 'report-sprint-all-sprint-3.yaml').read_text()


def test_report_sprint_prints_a_sprint_in_progress(
    capsys: pytest.CaptureFixture[str], time_machine: TimeMachineFixture
) -> None:
    # GIVEN All Sprint 2 runs from November 3rd to 17th, holding SAT-7, which SAT-4 blocks
    time_machine.move_to(parse('2026-11-10T12:00:00Z'), tick=False)

    # WHEN
    exit_code = main(['report', 'sprint', 'All Sprint 2'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == (RESOURCES / 'report-sprint-all-sprint-2.yaml').read_text()


def test_report_sprint_fails_for_a_sprint_it_doesnt_have(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['report', 'sprint', 'Sprint 9'])

    # THEN
    assert exit_code == 1
    assert capsys.readouterr().err == 'cat-herder report sprint: no sprint is called Sprint 9\n'

