from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from cat_herder.domain.time_entry import TimeEntry, TimeEntryFlag
from cat_herder.sources.errors import SourceError, SourceUnreachable
from cat_herder.sources.time_source import TimeSource
from cat_herder.sources.toggl import source
from cat_herder.sources.toggl.client import TogglClient
from cat_herder.sources.toggl.source import TogglSource
from tests.toggl_api import ADMIN_PROJECT, SAT_PROJECT, TOGGL_CONFIG, TogglApi

OCTOBER = (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))
CEST = timezone(timedelta(hours=2))


@pytest.fixture
def toggl_api() -> TogglApi:
    return TogglApi()


def test_fetch_time_entries_maps_the_finished_entries_of_those_spaces_from_every_page(
    toggl_api: TogglApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN pages of two rows, and an archived space
    monkeypatch.setattr(source, 'SEARCH_PAGE_SIZE', 2)
    cut = _source(toggl_api)

    # WHEN
    entries = cut.fetch_time_entries([SAT_PROJECT, ADMIN_PROJECT, 'Holidays'], *OCTOBER)

    # THEN 9009 is still running, and 9004 names two tickets
    assert [entry.id for entry in entries] == ['9001', '9002', '9003', '9004', '9005', '9006', '9007', '9008']
    assert entries[0] == TimeEntry(
        source='toggl',
        id='9001',
        space=SAT_PROJECT,
        person='456',
        description='SAT-7 Retry failed meteo imports',
        start=datetime(2026, 10, 20, 9, tzinfo=CEST),
        end=datetime(2026, 10, 20, 11, tzinfo=CEST),
        ticket_key='SAT-7',
    )
    assert (entries[3].ticket_key, entries[3].flags) == (None, {TimeEntryFlag.SEVERAL_TICKETS})
    assert (entries[2].ticket_key, entries[2].flags) == (None, set())


def test_fetch_time_entries_searches_a_day_more_on_each_side_and_keeps_those_starting_in_range(
    toggl_api: TogglApi,
) -> None:
    # GIVEN
    cut = _source(toggl_api)
    start, end = datetime(2026, 10, 21, tzinfo=CEST), datetime(2026, 10, 23, tzinfo=CEST)

    # WHEN
    entries = cut.fetch_time_entries([SAT_PROJECT], start, end)

    # THEN
    assert [entry.id for entry in entries] == ['9002', '9003']
    [search] = toggl_api.searches()
    assert (search['project_ids'], search['start_date'], search['end_date']) == ([101], '2026-10-19', '2026-10-23')


def test_fetch_time_entries_looks_up_the_project_ids_once(toggl_api: TogglApi) -> None:
    # GIVEN
    cut = _source(toggl_api)
    cut.fetch_time_entries([SAT_PROJECT], *OCTOBER)

    # WHEN
    cut.fetch_time_entries([SAT_PROJECT, ADMIN_PROJECT], *OCTOBER)

    # THEN
    assert [request.method for request in toggl_api.requests] == ['GET', 'POST', 'POST']


def test_fetch_time_entries_raises_source_unreachable_when_toggl_cant_be_reached(toggl_api: TogglApi) -> None:
    # GIVEN
    toggl_api.reachable = False
    cut = _source(toggl_api)

    # WHEN / THEN
    with pytest.raises(SourceUnreachable):
        cut.fetch_time_entries([SAT_PROJECT], *OCTOBER)


def test_fetch_time_entries_raises_source_error_when_toggl_answers_with_an_error(toggl_api: TogglApi) -> None:
    # GIVEN no quota left
    toggl_api.searches_left = 0
    cut = _source(toggl_api)

    # WHEN / THEN
    with pytest.raises(SourceError, match='HTTP 402 You have hit your hourly limit'):
        cut.fetch_time_entries([SAT_PROJECT], *OCTOBER)


def _source(toggl_api: TogglApi) -> TimeSource:
    return TogglSource(TOGGL_CONFIG, TogglClient(lambda: 'token', transport=httpx.MockTransport(toggl_api)))
