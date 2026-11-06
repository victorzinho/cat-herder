from collections.abc import Callable
from pathlib import Path

import pytest

from cat_herder.domain.config import Config, Project, TicketOrigin

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
