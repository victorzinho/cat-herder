import re

import pytest

from cat_herder.domain.config import CommandCredential, Credential, EnvCredential
from cat_herder.sources.credentials import read_credential
from cat_herder.sources.errors import CredentialsMissing


@pytest.mark.parametrize(
    ('credential', 'expected'),
    [
        pytest.param(EnvCredential(name='JIRA_TOKEN'), 'from-env', id='env'),
        pytest.param(CommandCredential(command="printf ' from command\\n'"), 'from command', id='command'),
    ],
)
def test_read_credential_reads_the_value(credential: Credential, expected: str) -> None:
    # WHEN
    value = read_credential('jira', credential, {'JIRA_TOKEN': 'from-env'})

    # THEN
    assert value == expected


@pytest.mark.parametrize(
    ('credential', 'message'),
    [
        pytest.param(EnvCredential(name='JIRA_TOKEN'), 'jira needs JIRA_TOKEN set', id='env-unset'),
        pytest.param(
            CommandCredential(command="sh -c 'echo locked >&2; exit 3'"),
            "jira credential command failed: sh -c 'echo locked >&2; exit 3': locked",
            id='command-fails',
        ),
        pytest.param(
            CommandCredential(command='true'),
            'jira credential command failed: true: exit code 0, no output',
            id='command-prints-nothing',
        ),
        pytest.param(
            CommandCredential(command='no-such-command-anywhere'),
            "jira credential command failed: no-such-command-anywhere: [Errno 2] No such file or directory: "
            "'no-such-command-anywhere'",
            id='command-missing',
        ),
    ],
)
def test_read_credential_raises_when_it_cant(credential: Credential, message: str) -> None:
    # WHEN / THEN
    with pytest.raises(CredentialsMissing, match=f'^{re.escape(message)}$'):
        read_credential('jira', credential, {})
