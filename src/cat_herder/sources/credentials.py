import shlex
import subprocess
from collections.abc import Mapping

from cat_herder.domain.config import CommandCredential, Credential, EnvCredential
from cat_herder.sources.errors import CredentialsMissing


def read_credential(source: str, credential: Credential, environ: Mapping[str, str]) -> str:
    """The credential's value: the environment variable's, or the command's output without surrounding whitespace.

    Raises:
        CredentialsMissing: if the variable isn't set, or the command fails or prints nothing.
    """
    match credential:
        case EnvCredential(name=name):
            if not (value := environ.get(name)):
                raise CredentialsMissing(f'{source} needs {name} set')
            return value
        case CommandCredential(command=command):
            try:
                result = subprocess.run(shlex.split(command), capture_output=True, text=True, check=False)
            except OSError as error:
                raise CredentialsMissing(f'{source} credential command failed: {command}: {error}') from error
            if result.returncode != 0 or not (value := result.stdout.strip()):
                problem = result.stderr.strip() or f'exit code {result.returncode}, no output'
                raise CredentialsMissing(f'{source} credential command failed: {command}: {problem}')
            return value
