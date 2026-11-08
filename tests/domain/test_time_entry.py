from datetime import datetime

import pytest

from tests.dates import parse
from tests.factories import new_sprint, new_time_entry


@pytest.mark.parametrize(('sprint_name', 'ticket_key', 'start', 'counts'), [
    pytest.param('Sprint 1', None, parse('2026-09-01T12:00:00Z'), True, id='names-it-outside-its-dates'),
    pytest.param('Sprint 2', 'SAT-1', parse('2026-10-05T12:00:00Z'), False, id='names-another'),
    pytest.param(None, 'SAT-1', parse('2026-10-05T12:00:00Z'), True, id='on-its-ticket'),
    pytest.param(None, 'SAT-2', parse('2026-10-05T12:00:00Z'), False, id='on-another-ticket'),
    pytest.param(None, 'SAT-1', parse('2026-09-05T12:00:00Z'), False, id='outside-its-dates'),
    pytest.param(None, None, parse('2026-10-05T12:00:00Z'), True, id='ticketless'),
])
def test_counts_in_sprint_follows_the_sprint_rules(
    sprint_name: str | None, ticket_key: str | None, start: datetime, counts: bool
) -> None:
    # GIVEN Sprint 1, from the 1st to the 12th, holding SAT-1 in the entry's project
    sprint = new_sprint(
        name='Sprint 1',
        start=parse('2026-10-01T12:00:00Z'),
        actual_end=parse('2026-10-12T12:00:00Z'),
    )
    entry = new_time_entry(sprint=sprint_name, ticket_key=ticket_key, start=start)

    # WHEN / THEN
    assert entry.counts_in_sprint(sprint, {'SAT-1'}) is counts


def test_counts_in_sprint_leaves_out_ticketless_hours_when_it_held_no_tickets_in_their_project() -> None:
    # GIVEN
    sprint = new_sprint(
        start=parse('2026-10-01T12:00:00Z'),
        actual_end=parse('2026-10-12T12:00:00Z')
    )
    entry = new_time_entry(start=parse('2026-10-05T12:00:00Z'))

    # WHEN / THEN
    assert entry.counts_in_sprint(sprint, set()) is False
