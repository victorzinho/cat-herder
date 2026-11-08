class SourceUnreachable(Exception):
    """The source couldn't be reached, or stopped answering: a DNS, connection, TLS or proxy failure, or a timeout."""


class SourceError(Exception):
    """The source answered, with an error. This includes running out of quota."""


class TicketNotFound(SourceError):
    """The source has no ticket with that key, so it's gone."""


class CredentialsMissing(Exception):
    """An environment variable the config names for a source's credentials isn't set."""


class WriteIncomplete(SourceError):
    """A write failed before applying all its changes. The message says which were applied and which weren't."""
