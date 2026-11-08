from datetime import datetime, timedelta

import pytest

from cat_herder.domain.ticket import Sprint, SprintState
from tests.dates import october, parse, september
from tests.factories import new_change, new_sprint, new_ticket


def test_as_of_undoes_the_changes_after_then() -> None:
    # GIVEN To do with 3 points and 4 h on the 1st, then In progress with 5 points and 8 h on the 3rd
    ticket = new_ticket(status='In progress', points=5, estimated_hours=8, changes=(
        new_change(field='status', before='To do', after='In progress', date=october(3)),
        new_change(field='points', before='3', after='5', date=october(3)),
        new_change(field='estimated_hours', before='4', after='8', date=october(3)),
    ))

    # WHEN
    as_of = ticket.as_of(october(2))

    # THEN
    assert (as_of.status, as_of.points, as_of.estimated_hours, as_of.changes) == ('To do', 3, 4, ())


def test_in_sprint_as_of_undoes_the_changes_to_sprints_after_then() -> None:
    # GIVEN added to Sprint 1 on the 1st, and carried over to Sprint 2 on the 3rd
    sprint_1, sprint_2 = new_sprint(id='1', name='Sprint 1'), new_sprint(id='2', name='Sprint 2')
    ticket = new_ticket(sprints=(sprint_1, sprint_2), changes=(
        new_change(field='sprints', before=None, after='1', date=october(1)),
        new_change(field='sprints', before='1', after='1, 2', date=october(3)),
    ))

    # WHEN
    held = [[ticket.in_sprint_as_of(each, day) for each in (sprint_1, sprint_2)] for day in (october(2), october(4))]

    # THEN
    assert held == [[True, False], [True, True]]


@pytest.mark.parametrize(('sprint', 'expected'), [
    pytest.param(new_sprint(id='3', start=september(25)), True, id='held-at-its-start'),
    pytest.param(new_sprint(id='3', start=october(5)), False, id='held-only-before-its-start'),
    pytest.param(new_sprint(id='1', start=september(25), actual_end=october(10)), True, id='added-while-it-ran'),
    pytest.param(new_sprint(id='2', state=SprintState.NOT_STARTED, start=october(20)), True, id='not-started-holds-it'),
])
def test_was_in_sprint_says_whether_the_sprint_held_the_ticket_while_it_ran(sprint: Sprint, expected: bool) -> None:
    # GIVEN in sprint 3 from September 20th, moved to 1 on October 2nd, and to 2 on the 12th
    ticket = new_ticket(sprints=(new_sprint(id='2'),), changes=(
        new_change(field='sprints', before=None, after='3', date=september(20)),
        new_change(field='sprints', before='3', after='1', date=october(2)),
        new_change(field='sprints', before='1', after='2', date=october(12)),
    ))

    # WHEN / THEN
    assert ticket.was_in_sprint(sprint) is expected


@pytest.mark.parametrize(('actual_end', 'duration'), [
    pytest.param(parse('2026-10-12T15:00:00Z'), timedelta(days=11, hours=6), id='ended'),
    pytest.param(None, timedelta(days=14), id='not-ended'),
])
def test_duration_runs_from_the_start_to_the_actual_or_planned_end(
    actual_end: datetime | None, duration: timedelta
) -> None:
    # GIVEN planned for the 1st to the 15th
    sprint = new_sprint(start=october(1), planned_end=october(15), actual_end=actual_end)

    # WHEN / THEN
    assert sprint.duration == duration


def test_duration_is_none_without_dates() -> None:
    # GIVEN
    sprint = new_sprint(start=None, planned_end=None)

    # WHEN / THEN
    assert sprint.duration is None


@pytest.mark.parametrize(('moment', 'covers'), [
    pytest.param(parse('2026-10-01T09:00:00Z'), True, id='start'),
    pytest.param(parse('2026-10-12T11:00:00+02:00'), True, id='end-in-another-offset'),
    pytest.param(parse('2026-10-01T08:59:00Z'), False, id='before-the-start'),
    pytest.param(parse('2026-10-12T09:01:00Z'), False, id='after-the-end'),
])
def test_covers_the_moments_from_start_to_actual_end(moment: datetime, covers: bool) -> None:
    # GIVEN
    sprint = new_sprint(start=october(1), actual_end=october(12))

    # WHEN / THEN
    assert sprint.covers(moment) is covers


@pytest.mark.parametrize(('state', 'moment', 'time_left'), [
    pytest.param(SprintState.NOT_STARTED, parse('2026-10-01T09:00:00Z'), timedelta(days=14), id='not-started'),
    pytest.param(SprintState.IN_PROGRESS, parse('2026-10-10T09:00:00Z'), timedelta(days=6), id='in-progress'),
    pytest.param(SprintState.IN_PROGRESS, parse('2026-10-17T09:00:00Z'), timedelta(), id='past-the-planned-end'),
    pytest.param(SprintState.ENDED, parse('2026-10-16T09:00:00Z'), timedelta(), id='ended'),
])
def test_time_left_runs_to_the_planned_end_while_in_progress(
    state: SprintState, moment: datetime, time_left: timedelta
) -> None:
    # GIVEN planned from the 2nd to the 16th
    sprint = new_sprint(state=state, start=october(2), planned_end=october(16))

    # WHEN / THEN
    assert sprint.time_left(moment) == time_left


def test_time_left_is_none_without_dates() -> None:
    # GIVEN
    sprint = new_sprint(state=SprintState.NOT_STARTED, start=None, planned_end=None)

    # WHEN / THEN
    assert sprint.time_left(october(1)) is None
