from pathlib import Path

import pytest

from cat_herder.domain.config import Config
from cat_herder.sources.errors import CredentialsMissing
from cat_herder.sources.factory import build_ticket_sources
from tests.factories import new_toggl_source_config
from tests.jira_api import JIRA_CONFIG

CONFIG = Config(data_dir=Path(), sources=(JIRA_CONFIG, new_toggl_source_config()), projects=())


def test_build_ticket_sources_builds_the_ticket_sources_without_reading_credentials() -> None:
    # GIVEN no credentials set
    environ: dict[str, str] = {}

    # WHEN
    sources = build_ticket_sources(CONFIG, environ)

    # THEN
    assert [source.slug for source in sources] == ['jira']


def test_a_built_source_reads_its_credentials_when_it_first_contacts_its_source() -> None:
    # GIVEN only the email set
    [jira] = build_ticket_sources(CONFIG, {'JIRA_EMAIL': 'ana@example.com'})

    # WHEN / THEN
    with pytest.raises(CredentialsMissing, match='^jira needs JIRA_TOKEN set$'):
        jira.fetch_ticket('SAT-7')
