from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from cat_herder.domain.config import Config, Project, SourceConfig, TicketOrigin, TimeOrigin
from tests.factories import new_jira_source_config, new_ticket, new_time_entry, new_toggl_source_config


def test_time_source_returns_the_time_source_with_that_slug() -> None:
    # GIVEN
    toggl = new_toggl_source_config(slug='toggl')
    config = _config(sources=(new_jira_source_config(), toggl))

    # WHEN / THEN
    assert config.time_source('toggl') == toggl


def test_project_returns_the_one_with_that_slug() -> None:
    # GIVEN
    sat = _ticket_project('sat', 'jira', 'SAT')
    config = _config(projects=(sat, _ticket_project('web', 'jira', 'WEB')))

    # WHEN / THEN
    assert config.project('sat') == sat


@pytest.mark.parametrize(('lookup', 'slug'), [
    pytest.param(Config.source, 'nope', id='source'),
    pytest.param(Config.time_source, 'nope', id='time-source'),
    pytest.param(Config.time_source, 'jira', id='time-source-of-a-ticket-source'),
    pytest.param(Config.project, 'nope', id='project'),
])
def test_lookups_raise_key_error_for_a_slug_without_one(lookup: Callable[[Config, str], object], slug: str) -> None:
    # GIVEN
    config = _config(
        sources=(new_jira_source_config(slug='jira'),),
        projects=(_ticket_project('sat', 'jira', 'SAT'),)
    )

    # WHEN / THEN
    with pytest.raises(KeyError):
        lookup(config, slug)


def test_project_of_ticket_returns_the_project_with_tickets_in_its_space() -> None:
    # GIVEN
    sat = _ticket_project('sat', 'jira', 'SAT')
    config = _config(projects=(sat,))

    # WHEN
    project_sat = config.project_of_ticket(new_ticket(source='jira', space='SAT'))
    project_web = config.project_of_ticket(new_ticket(source='jira', space='WEB'))

    # THEN
    assert (project_sat, project_web) == (sat, None)


def test_project_of_time_entry_returns_the_project_with_time_in_its_space() -> None:
    # GIVEN sat with two Toggl spaces, and other with a space in another time source
    sat = _time_project('sat', 'toggl', 'SAT-2025', 'SAT-2026')
    other_project = _time_project('other', 'harvest', 'Other')
    config = _config(projects=(sat, other_project))

    # WHEN
    project_sat = config.project_of_time_entry(new_time_entry(source='toggl', space='SAT-2026'))
    project_other = config.project_of_time_entry(new_time_entry(source='toggl', space='Other'))

    # THEN
    assert (project_sat, project_other) == (sat, None)


@pytest.mark.parametrize(('prefix', 'expected'), [
        pytest.param('SAT', ('jira', 'other'), id='in-two-sources'),
        pytest.param('WEB', ('jira',), id='in-one-source'),
        pytest.param('OPS', ('jira', 'other'), id='in-no-project'),
])
def test_ticket_sources_for_key_prefix_returns_the_sources_it_can_come_from(
    prefix: str, expected: tuple[str, ...]
) -> None:
    # GIVEN SAT in jira and other, WEB in jira, and a Toggl source, which has no tickets
    config = _config(
        sources=(new_jira_source_config(slug='other'), new_jira_source_config(slug='jira'), new_toggl_source_config()),
        projects=(
            _ticket_project('sat', 'jira', 'SAT'),
            _ticket_project('web', 'jira', 'WEB'),
            _ticket_project('sat-meteo', 'other', 'SAT'),
        ),
    )

    # WHEN
    sources = config.ticket_sources_for_key_prefix(prefix)

    # THEN
    assert sorted(sources) == sorted(expected)


def _config(sources: Iterable[SourceConfig] = (), projects: Iterable[Project] = ()) -> Config:
    return Config(data_dir=Path('/data'), sources=tuple(sources), projects=tuple(projects))


def _ticket_project(slug: str, source: str, space: str) -> Project:
    return Project(slug=slug, tickets=TicketOrigin(source=source, space=space), time=None)


def _time_project(slug: str, source: str, *spaces: str) -> Project:
    return Project(slug=slug, tickets=None, time=TimeOrigin(source=source, spaces=spaces))
