from collections.abc import Iterable

from cat_herder.domain.config import Config


def unknown_projects(config: Config, slugs: Iterable[str]) -> list[str]:
    """Those of the slugs no configured project has, in order."""
    known = {project.slug for project in config.projects}
    return [slug for slug in slugs if slug not in known]
