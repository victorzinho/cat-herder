from collections.abc import Mapping

from cat_herder.domain.config import Config, JiraSourceConfig, TicketSourceConfig
from cat_herder.sources.credentials import read_credential
from cat_herder.sources.jira.client import JiraClient
from cat_herder.sources.jira.source import JiraSource
from cat_herder.sources.ticket_source import TicketSource


def build_ticket_sources(config: Config, environ: Mapping[str, str]) -> list[TicketSource]:
    """The config's ticket sources. Each reads its credentials when it first contacts its source."""
    return [_ticket_source(source, environ) for source in config.sources if isinstance(source, TicketSourceConfig)]


def _ticket_source(config: TicketSourceConfig, environ: Mapping[str, str]) -> TicketSource:
    match config:
        case JiraSourceConfig(slug=slug, email=email, token=token):
            return JiraSource(
                config,
                JiraClient(
                    config.url,
                    lambda: (read_credential(slug, email, environ), read_credential(slug, token, environ)),
                ),
            )
        case _:
            raise TypeError(f'{config.slug} is a {type(config).__name__}, which has no ticket source')
