import re
import zlib
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy
import yaml
from jsonschema import Draft202012Validator

from cat_herder.domain.config import Access, EnvCredential, JiraSourceConfig, TimeOrigin, TogglSourceConfig
from cat_herder.domain.ticket import (
    Attachment,
    Change,
    Comment,
    Link,
    Sprint,
    SprintState,
    Ticket,
    TicketSummary,
)
from cat_herder.domain.time_entry import TimeEntry
from cat_herder.embeddings.encoder import Vectors


def parse(value: str) -> datetime:
    """An aware datetime from an ISO string with its offset, such as 2026-10-01T09:00:00Z.

    Raises:
        ValueError: if the string isn't ISO, or has no offset.
    """
    parsed = datetime.fromisoformat(value)
    if not parsed.tzinfo:
        raise ValueError(f'{value} has no offset')
    return parsed


def august(day: int) -> datetime:
    """That day of August 2026, at 09:00 UTC, as for the other months."""
    return parse(f'2026-08-{day:02}T09:00:00Z')


def september(day: int) -> datetime:
    return parse(f'2026-09-{day:02}T09:00:00Z')


def october(day: int) -> datetime:
    return parse(f'2026-10-{day:02}T09:00:00Z')


def november(day: int) -> datetime:
    return parse(f'2026-11-{day:02}T09:00:00Z')


# Valid defaults. A test sets every field it asserts on or depends on, and leaves the rest to these.
_DATE = parse('2026-10-01T09:00:00Z')
_SPRINT = Sprint(
    source='jira',
    id='1',
    name='Sprint 1',
    state=SprintState.IN_PROGRESS,
    start=_DATE,
    planned_end=parse('2026-10-15T09:00:00Z'),
)
_COMMENT = Comment(author='account-ana', created=_DATE, body='A comment')
_ATTACHMENT = Attachment(id='1', filename='notes.txt', size=1024, created=_DATE)
_TICKET = Ticket(
    source='jira',
    key='SAT-1',
    space='SAT',
    title='A ticket',
    type='Task',
    status='To do',
    created=_DATE,
    updated=_DATE,
)
_TICKET_SUMMARY = TicketSummary(source='jira', key='SAT-2', title='Another ticket', status='To do', type='Task')
_LINK = Link(from_key='SAT-1', relation='blocks', to_key='SAT-2')
_JIRA_SOURCE_CONFIG = JiraSourceConfig(
    slug='jira',
    access=Access.FULL,
    fetch_window_seconds=60,
    done_statuses=('Done',),
    url='https://example.atlassian.net',
    email=EnvCredential(name='JIRA_EMAIL'),
    token=EnvCredential(name='JIRA_TOKEN'),
)
_TOGGL_SOURCE_CONFIG = TogglSourceConfig(
    slug='toggl',
    access=Access.READ_ONLY,
    fetch_window_seconds=900,
    workspace=1,
    history_from=parse('2026-01-01T00:00:00Z'),
    token=EnvCredential(name='TOGGL_TOKEN'),
)
_TIME_ENTRY = TimeEntry(
    source='toggl',
    id='1',
    space='SAT',
    person='456',
    description='Some work',
    start=_DATE,
    end=_DATE + timedelta(hours=1),
)
_TIME_ORIGIN = TimeOrigin(source='toggl', spaces=('SAT',))
_CHANGE = Change(field='status', author='account-ana', before='To do', after='In progress', date=_DATE)


def new_sprint(**overrides: Any) -> Sprint:
    return replace(_SPRINT, **overrides)


def new_comment(**overrides: Any) -> Comment:
    return replace(_COMMENT, **overrides)


def new_attachment(**overrides: Any) -> Attachment:
    return replace(_ATTACHMENT, **overrides)


def new_ticket(**overrides: Any) -> Ticket:
    return replace(_TICKET, **overrides)


def new_ticket_summary(**overrides: Any) -> TicketSummary:
    return replace(_TICKET_SUMMARY, **overrides)


def new_link(**overrides: Any) -> Link:
    return replace(_LINK, **overrides)


def new_change(**overrides: Any) -> Change:
    return replace(_CHANGE, **overrides)


def new_jira_source_config(**overrides: Any) -> JiraSourceConfig:
    return replace(_JIRA_SOURCE_CONFIG, **overrides)


def new_toggl_source_config(**overrides: Any) -> TogglSourceConfig:
    return replace(_TOGGL_SOURCE_CONFIG, **overrides)


def new_time_entry(hours: float | None = None, **overrides: Any) -> TimeEntry:
    """With hours, it ends that long after its start."""
    entry = replace(_TIME_ENTRY, **overrides)
    return replace(entry, end=entry.start + timedelta(hours=hours)) if hours is not None else entry


def new_time_origin(**overrides: Any) -> TimeOrigin:
    return replace(_TIME_ORIGIN, **overrides)


CONFIG_EXAMPLE = Path(__file__).parents[1] / 'docs' / 'config.example.yaml'


def resource(name: str) -> Path:
    """The test resource at that path, relative to tests/resources, such as cli/workspace/config.yaml."""
    return Path(__file__).parent / 'resources' / name


def config_schema() -> Draft202012Validator:
    """A validator for the config's schema, checking formats too."""
    return Draft202012Validator(
        yaml.safe_load(files('cat_herder.store').joinpath('schemas', 'config.schema.yaml').read_text()),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


class FakeEncoder:
    """An Encoder whose tokens are words, and whose meaning is theirs: words in one of the groups of synonyms embed
    alike, and any other word as itself, so texts sharing no word or synonym are unrelated. It reads max_tokens words,
    its two markers included, and records every text it encodes, in encoded.
    """

    def __init__(self, synonyms: Sequence[Sequence[str]] = (), max_tokens: int = 64, model: str = 'fake') -> None:
        self._concept = {word: group[0] for group in synonyms for word in group}
        self._max_tokens = max_tokens
        self._model = model
        self.encoded: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def min_similarity(self) -> float:
        return 0.0

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return [match.span() for match in re.finditer(r'\w+', text)]

    def encode(self, texts: Sequence[str]) -> Vectors:
        self.encoded += texts
        vectors = numpy.zeros((len(texts), 256), dtype=numpy.float32)
        for row, text in enumerate(texts):
            words: list[str] = re.findall(r'\w+', text.lower())
            for word in words[:self._max_tokens - 2]:
                vectors[row, zlib.crc32(self._concept.get(word, word).encode()) % 256] += 1
        return (vectors / numpy.maximum(numpy.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)).astype(numpy.float32)
