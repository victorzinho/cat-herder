from datetime import UTC, datetime
from typing import Any

import yaml

from cat_herder.domain.ticket import CustomValue

NO_TIME_SOURCE = 'no time source'
HOURS_DECIMALS = 2


class Block(dict[str, Any]):
    """A mapping dumped in block style, so its multi-line values can be literal blocks."""


class Flow(dict[str, Any]):
    """A mapping dumped in flow style, on one line even if it holds collections."""


def dump(document: object) -> str:
    """The document as the docs' examples show YAML: in order, with collections of scalars in flow style."""
    return yaml.dump(document, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000)


def number(value: CustomValue) -> CustomValue | int:
    """A whole float as an int, so 5.0 reads as 5."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def timestamp(value: datetime) -> str:
    """In UTC, to the second."""
    return value.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def hours(value: float | None) -> CustomValue | int:
    """Rounded to two decimals, and whole as an int."""
    return number(round(value, HOURS_DECIMALS)) if value is not None else None


class _Dumper(yaml.SafeDumper):
    # Indents list items under their key, as in the docs' examples.
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    # types-PyYAML leaves represent_scalar's value untyped.
    style = '|' if '\n' in value else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style)  # pyright: ignore[reportUnknownMemberType]


def _represent_block(dumper: yaml.SafeDumper, value: Block) -> yaml.MappingNode:
    return dumper.represent_mapping('tag:yaml.org,2002:map', value, flow_style=False)


def _represent_flow(dumper: yaml.SafeDumper, value: Flow) -> yaml.MappingNode:
    return dumper.represent_mapping('tag:yaml.org,2002:map', value, flow_style=True)


_Dumper.add_representer(str, _represent_str)
_Dumper.add_representer(Block, _represent_block)
_Dumper.add_representer(Flow, _represent_flow)
