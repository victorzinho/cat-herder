from collections.abc import Callable
from pathlib import Path

import pytest

from cat_herder.domain.config import Config, Project, TicketOrigin
from tests.factories import new_jira_source_config, new_toggl_source_config

SAT = Project(slug='sat', tickets=TicketOrigin(source='jira', space='SAT'), time=None)
CONFIG = Config(data_dir=Path('/data'), sources=(), projects=(SAT,))


def test_project_returns_the_one_with_that_slug() -> None:
    # WHEN / THEN
    assert CONFIG.project('sat') == SAT


@pytest.mark.parametrize('lookup', [
    pytest.param(Config.source, id='source'),
    pytest.param(Config.project, id='project')
])
def test_lookups_raise_key_error_for_an_undefined_slug(lookup: Callable[[Config, str], object]) -> None:
    # WHEN / THEN
    with pytest.raises(KeyError):
        lookup(CONFIG, 'nope')


def test_project_for_returns_the_project_with_tickets_in_that_space() -> None:
    # WHEN / THEN
    assert (CONFIG.project_for('jira', 'SAT'), CONFIG.project_for('jira', 'WEB')) == (SAT, None)


@pytest.mark.parametrize(('prefix', 'expected'), [
        pytest.param('SAT', ('jira', 'other'), id='in-two-sources'),
        pytest.param('WEB', ('jira',), id='in-one-source'),
        pytest.param('OPS', ('jira', 'other'), id='in-no-project'),
])
def test_sources_for_key_prefix_returns_the_sources_it_can_come_from(prefix: str, expected: tuple[str, ...]) -> None:
    # GIVEN SAT in jira and other, WEB in jira, and a Toggl source, which has no tickets
    config = Config(
        data_dir=Path('/data'),
        sources=(new_jira_source_config(slug='other'), new_jira_source_config(), new_toggl_source_config()),
        projects=(
            SAT,
            Project(slug='web', tickets=TicketOrigin(source='jira', space='WEB'), time=None),
            Project(slug='sat-meteo', tickets=TicketOrigin(source='other', space='SAT'), time=None),
        ),
    )

    # WHEN
    sources = config.sources_for_key_prefix(prefix)

    # THEN
    assert sorted(sources) == sorted(expected)

