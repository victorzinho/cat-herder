from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from cat_herder.domain.config import (
    Access,
    Config,
    ConfigPart,
    Person,
    Project,
    Repository,
    SourceConfig,
    SourceSummary,
    TicketOrigin,
    TimeOrigin,
    WriteNotAllowed,
)
from cat_herder.domain.ticket import Change
from tests.helpers import (
    new_change,
    new_jira_source_config,
    new_ticket,
    new_time_entry,
    new_toggl_source_config,
    parse,
)


def test_ticket_source_returns_the_ticket_source_with_that_slug() -> None:
    # GIVEN
    jira = new_jira_source_config(slug='jira')
    config = _config(sources=(jira, new_toggl_source_config()))

    # WHEN / THEN
    assert config.ticket_source('jira') == jira


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
    pytest.param(Config.ticket_source, 'nope', id='ticket-source'),
    pytest.param(Config.ticket_source, 'toggl', id='ticket-source-of-a-time-source'),
    pytest.param(Config.time_source, 'nope', id='time-source'),
    pytest.param(Config.time_source, 'jira', id='time-source-of-a-ticket-source'),
    pytest.param(Config.project, 'nope', id='project'),
    pytest.param(Config.for_project, 'nope', id='for-project'),
])
def test_lookups_raise_key_error_for_a_slug_without_one(lookup: Callable[[Config, str], object], slug: str) -> None:
    # GIVEN
    config = _config(
        sources=(new_jira_source_config(slug='jira'), new_toggl_source_config(slug='toggl')),
        projects=(_ticket_project('sat', 'jira', 'SAT'),)
    )

    # WHEN / THEN
    with pytest.raises(KeyError):
        lookup(config, slug)


def test_for_project_keeps_that_project_its_repositories_and_a_summary_of_its_sources() -> None:
    # GIVEN
    config = _workspace()

    # WHEN
    part = config.for_project('web')

    # THEN
    assert part == ConfigPart(
        sources=(SourceSummary(slug='jira', type='jira', access=Access.FULL),),
        repositories=(_repository('website'),),
        projects=(config.project('web'),),
    )


@pytest.mark.parametrize(('repository', 'sources', 'projects', 'repositories'), [
    pytest.param('sat', ('jira', 'toggl'), ('sat',), ('sat', 'sat-meteo'), id='in-a-project'),
    pytest.param('sat-meteo', ('jira', 'toggl'), ('sat', 'ops'), ('sat', 'sat-meteo'), id='in-several-projects'),
    pytest.param('tools', (), (), ('tools',), id='in-no-project'),
])
def test_for_repository_keeps_the_projects_with_it_their_repositories_and_a_summary_of_their_sources(
    repository: str, sources: tuple[str, ...], projects: tuple[str, ...], repositories: tuple[str, ...]
) -> None:
    # GIVEN
    config = _workspace()

    # WHEN
    part = config.for_repository(repository)

    # THEN
    assert part == ConfigPart(
        sources=tuple(config.source(slug).summary() for slug in sources),
        repositories=tuple(_repository(slug) for slug in repositories),
        projects=tuple(config.project(slug) for slug in projects),
    )


def test_check_writable_rejects_a_read_only_source() -> None:
    # GIVEN
    config = _config(
        sources=(new_jira_source_config(access=Access.FULL), new_toggl_source_config(access=Access.READ_ONLY))
    )

    # WHEN / THEN
    with pytest.raises(WriteNotAllowed, match='^toggl is read-only in the config$'):
        config.check_writable('toggl')


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


@pytest.mark.parametrize(('project_slugs', 'origins'), [
    pytest.param((), [('jira', 'SAT'), ('jira', 'WEB'), ('other', 'SAT')], id='every-project'),
    pytest.param(('web', 'sat-meteo'), [('jira', 'WEB'), ('other', 'SAT')], id='those-projects'),
])
def test_ticket_origins_are_those_of_the_projects_each_once_sorted(
    project_slugs: tuple[str, ...], origins: list[tuple[str, str]]
) -> None:
    # GIVEN web and sat-meteo-web sharing WEB, and admin with time only
    config = _config(projects=(
        _ticket_project('web', 'jira', 'WEB'),
        _ticket_project('sat-meteo', 'other', 'SAT'),
        _ticket_project('sat', 'jira', 'SAT'),
        _ticket_project('sat-meteo-web', 'jira', 'WEB'),
        _time_project('admin', 'toggl', 'Admin'),
    ))

    # WHEN / THEN
    expected = [TicketOrigin(source=source, space=space) for source, space in origins]
    assert config.ticket_origins(project_slugs) == expected


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


@pytest.mark.parametrize(('status', 'changes', 'expected'), [
    pytest.param(
        'Done',
        (
            new_change(field='status', before='To do', after='Done', date=parse('2026-10-02T00:00:00Z')),
            new_change(field='status', before='Done', after='To do', date=parse('2026-10-03T00:00:00Z')),
            new_change(field='status', before='To do', after='Done', date=parse('2026-10-04T00:00:00Z')),
        ),
        parse('2026-10-04T00:00:00Z'),
        id='last-change-into-a-done-status',
    ),
    pytest.param('Done', (), parse('2026-10-01T00:00:00Z'), id='created-without-a-change-into-one'),
    pytest.param('To do', (), None, id='not-done'),
])
def test_done_date_is_when_the_ticket_was_done(
    status: str, changes: tuple[Change, ...], expected: datetime | None
) -> None:
    # GIVEN
    ticket = new_ticket(status=status, created=parse('2026-10-01T00:00:00Z'), changes=changes)

    # WHEN / THEN
    assert new_jira_source_config(done_statuses=('Done',)).done_date(ticket) == expected


@pytest.mark.parametrize(('identity', 'name'), [
    pytest.param('456', 'ana', id='configured'),
    pytest.param('999', 'unknown (999)', id='not-configured'),
    pytest.param(None, 'unknown', id='no-identity'),
])
def test_person_name_is_the_slug_of_the_person_with_that_identity(identity: str | None, name: str) -> None:
    # GIVEN ana, with 456 in Toggl
    config = replace(_config(), people=(Person(slug='ana', identity_by_source={'toggl': 456}),))

    # WHEN / THEN
    assert config.person_name('toggl', identity) == name


@pytest.mark.parametrize(('project_slug', 'capacity'), [
    pytest.param(None, 40, id='total'),
    pytest.param('sat', 10, id='project'),
    pytest.param('web', 0, id='project-without-capacity'),
])
def test_capacity_is_the_weekly_hours_over_the_period(project_slug: str | None, capacity: float) -> None:
    # GIVEN 20 h a week, 5 of them on sat
    person = Person(slug='ana', identity_by_source={}, weekly_hours=20, hours_by_project={'sat': 5})

    # WHEN / THEN
    assert person.capacity(timedelta(weeks=2), project_slug) == capacity


def _config(sources: Iterable[SourceConfig] = (), projects: Iterable[Project] = ()) -> Config:
    return Config(data_dir=Path('/data'), sources=tuple(sources), projects=tuple(projects))


def _ticket_project(slug: str, source: str, space: str) -> Project:
    return Project(slug=slug, tickets=TicketOrigin(source=source, space=space), time=None)


def _time_project(slug: str, source: str, *spaces: str) -> Project:
    return Project(slug=slug, tickets=None, time=TimeOrigin(source=source, spaces=spaces))


def _workspace() -> Config:
    """sat (jira and toggl) has sat and sat-meteo; ops (toggl) has sat-meteo; web (jira) has website; no project has
    tools, and none uses the source unused. It has a person, which no part keeps.
    """
    return Config(
        data_dir=Path('/data'),
        sources=(
            new_jira_source_config(slug='jira'),
            new_toggl_source_config(slug='toggl'),
            new_jira_source_config(slug='unused'),
        ),
        projects=(
            Project(
                slug='sat',
                tickets=TicketOrigin(source='jira', space='SAT'),
                time=TimeOrigin(source='toggl', spaces=('SAT',)),
                repositories=('sat', 'sat-meteo'),
            ),
            replace(_time_project('ops', 'toggl', 'OPS'), repositories=('sat-meteo',)),
            replace(_ticket_project('web', 'jira', 'WEB'), repositories=('website',)),
        ),
        people=(Person(slug='ana', identity_by_source={'jira': 'ana'}),),
        repositories=tuple(_repository(slug) for slug in ('sat', 'sat-meteo', 'website', 'tools')),
    )


def _repository(slug: str) -> Repository:
    return Repository(slug=slug, path=Path('/code') / slug)
