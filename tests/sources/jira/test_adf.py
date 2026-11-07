import json
from pathlib import Path

from cat_herder.sources.jira.adf import adf_to_markdown

RESOURCES = Path(__file__).parents[2] / 'resources' / 'sources' / 'jira'


def test_adf_to_markdown_renders_every_node_type() -> None:
    # GIVEN a document with every node type Jira's editor produces, plus media and a layout with no markdown equivalent
    document = json.loads((RESOURCES / 'every-node.json').read_text())

    # WHEN
    markdown = adf_to_markdown(document)

    # THEN media are left out, and the layout renders its content
    assert markdown == (RESOURCES / 'every-node.md').read_text().rstrip('\n')
