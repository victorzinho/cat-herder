from datetime import datetime, timedelta

import pytest

from tests.dates import parse
from tests.factories import new_change, new_sprint, new_ticket


def test_as_of_undoes_the_changes_after_then() -> None:
    # GIVEN To do with 3 points and 4 h on the 1st, then In progress with 5 points and 8 h on the 3rd
    ticket = new_ticket(status='In progress', points=5, estimated_hours=8, changes=(
        new_change(field='status', before='To do', after='In progress', date=_october(3)),
        new_change(field='points', before='3', after='5', date=_october(3)),
        new_change(field='estimated_hours', before='4', after='8', date=_october(3)),
    ))

    # WHEN
    as_of = ticket.as_of(_october(2))

    # THEN
    assert (as_of.status, as_of.points, as_of.estimated_hours, as_of.changes) == ('To do', 3, 4, ())


def test_sprint_names_as_of_undoes_the_changes_to_sprints_after_then() -> None:
    # GIVEN added to Sprint 1 on the 1st, and carried over to Sprint 2 on the 3rd
    sprints = (
        new_sprint(id='1', name='Sprint 1'),
        new_sprint(id='2', name='Sprint 2')
    )
    ticket = new_ticket(sprints=sprints, changes=(
        new_change(field='sprints', before=None, after='Sprint 1', date=_october(1)),
        new_change(field='sprints', before='Sprint 1', after='Sprint 1, Sprint 2', date=_october(3)),
    ))

    # WHEN
    names = [ticket.sprint_names_as_of(day) for day in (_october(2), _october(4))]

    # THEN
    assert names == [{'Sprint 1'}, {'Sprint 1', 'Sprint 2'}]


@pytest.mark.parametrize(('name', 'expected'), [
    pytest.param('Sprint 2', True, id='holds-it'),
    pytest.param('Sprint 1', True, id='held-it'),
    pytest.param('Sprint 3', False, id='never'),
])
def test_was_in_sprint_says_whether_the_sprint_holds_or_ever_held_the_ticket(name: str, expected: bool) -> None:
    # GIVEN moved from Sprint 1 to Sprint 2
    ticket = new_ticket(sprints=(new_sprint(name='Sprint 2'),), changes=(
        new_change(field='sprints', before='Sprint 1', after='Sprint 2'),
    ))

    # WHEN / THEN
    assert ticket.was_in_sprint(name) is expected


@pytest.mark.parametrize(('actual_end', 'duration'), [
    pytest.param(parse('2026-10-12T18:00:00Z'), timedelta(days=11, hours=6), id='ended'),
    pytest.param(None, timedelta(days=14), id='not-ended'),
])
def test_duration_runs_from_the_start_to_the_actual_or_planned_end(
    actual_end: datetime | None, duration: timedelta
) -> None:
    # GIVEN planned for the 1st to the 15th
    sprint = new_sprint(start=_october(1), planned_end=_october(15), actual_end=actual_end)

    # WHEN / THEN
    assert sprint.duration == duration


def test_duration_is_none_without_dates() -> None:
    # GIVEN
    sprint = new_sprint(start=None, planned_end=None)

    # WHEN / THEN
    assert sprint.duration is None


@pytest.mark.parametrize(('moment', 'covers'), [
    pytest.param(parse('2026-10-01T12:00:00Z'), True, id='start'),
    pytest.param(parse('2026-10-12T14:00:00+02:00'), True, id='end-in-another-offset'),
    pytest.param(parse('2026-10-01T11:59:00Z'), False, id='before-the-start'),
    pytest.param(parse('2026-10-12T12:01:00Z'), False, id='after-the-end'),
])
def test_covers_the_moments_from_start_to_actual_end(moment: datetime, covers: bool) -> None:
    # GIVEN
    sprint = new_sprint(start=_october(1), actual_end=_october(12))

    # WHEN / THEN
    assert sprint.covers(moment) is covers


def _october(day: int) -> datetime:
    return parse(f'2026-10-{day:02}T12:00:00Z')
