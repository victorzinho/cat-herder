import argparse
from importlib.metadata import version


def main(argv: list[str] | None = None) -> int:
    """Run the cat-herder command line; argv defaults to sys.argv.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(
        prog='cat-herder', description='Tickets and hours from separate tools, such as Jira and Toggl, in one place.'
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {version("cat-herder")}')
    parser.parse_args(argv)
    parser.print_help()
    return 0
