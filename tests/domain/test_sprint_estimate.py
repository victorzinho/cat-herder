from datetime import datetime

import pytest

from cat_herder.domain.sprint_estimate import reestimated_by, sprint_estimate
from cat_herder.domain.ticket import Sprint
from tests.dates import october, parse
from tests.factories import new_change, new_sprint, new_ticket, new_time_entry


@pytest.mark.parametrize(('sprint', 'estimated_hours', 'estimate'), [
    pytest.param(new_sprint(name='Sprint 1', start=parse('2026-10-05T09:00:00Z')), 10, 6, id='held'),
    pytest.param(new_sprint(name='Sprint 1', start=None), 10, 3, id='no-start'),
    pytest.param(new_sprint(id='9', name='Sprint 9', start=parse('2026-10-05T09:00:00Z')), 10, 0, id='not-held'),
    pytest.param(new_sprint(name='Sprint 1', start=parse('2026-10-05T09:00:00Z')), None, None, id='no-estimate'),
])
def test_sprint_estimate_leaves_out_the_hours_logged_before_the_sprint(
    sprint: Sprint, estimated_hours: float | None, estimate: float | None
) -> None:
    # GIVEN
    ticket = new_ticket(key='SAT-1', estimated_hours=estimated_hours, sprints=(new_sprint(name='Sprint 1'),))
    entries = [
        new_time_entry(ticket_key='SAT-1', start=october(1), hours=4),
        new_time_entry(ticket_key='SAT-1', start=october(6), hours=3),
        new_time_entry(ticket_key='SAT-2', start=october(1), hours=2),
    ]

    # WHEN / THEN
    assert sprint_estimate(ticket, sprint, october(7), entries) == estimate


@pytest.mark.parametrize(('changed', 'by'), [
    pytest.param(parse('2026-10-05T20:00:00Z'), 0, id='while-planning'),
    pytest.param(parse('2026-10-07T09:00:00Z'), 4, id='after-planning'),
])
def test_reestimated_by_counts_the_changes_after_planning(changed: datetime, by: float) -> None:
    # GIVEN
    sprint = new_sprint(name='Sprint 1', start=october(5))
    ticket = new_ticket(key='SAT-1', estimated_hours=12, sprints=(sprint,), changes=(
        new_change(field='estimated_hours', before='8', after='12', date=changed),
    ))

    # WHEN / THEN
    assert reestimated_by(ticket, sprint, october(8), []) == by
