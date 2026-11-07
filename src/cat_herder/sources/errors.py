class SourceUnreachable(Exception):
    """The source couldn't be reached: a DNS failure, a connect timeout or a TLS failure."""


class SourceError(Exception):
    """The source answered, with an error. This includes running out of quota."""


class TicketNotFound(SourceError):
    """The source has no ticket with that key, so it's gone."""


class CredentialsMissing(Exception):
    """An environment variable the config names for a source's credentials isn't set."""
