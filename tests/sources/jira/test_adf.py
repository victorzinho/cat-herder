import json
from pathlib import Path

from cat_herder.sources.jira.adf import adf_to_markdown, markdown_to_adf

RESOURCES = Path(__file__).parents[2] / 'resources' / 'sources' / 'jira'


def test_adf_to_markdown_renders_every_node_type() -> None:
    # GIVEN a document with every node type Jira's editor produces, plus media and a layout with no markdown equivalent
    document = json.loads((RESOURCES / 'every-node.json').read_text())

    # WHEN
    markdown = adf_to_markdown(document)

    # THEN media are left out, and the layout renders its content
    assert markdown == (RESOURCES / 'every-node.md').read_text().rstrip('\n')


def test_markdown_to_adf_turns_what_adf_to_markdown_renders_back_into_the_same_markdown() -> None:
    # GIVEN markdown with every block and mark adf_to_markdown renders, except task lists
    markdown = (RESOURCES / 'round-trip.md').read_text().rstrip('\n')

    # WHEN
    document = markdown_to_adf(markdown)

    # THEN
    assert adf_to_markdown(document) == markdown


def test_markdown_to_adf_keeps_line_breaks_and_only_links_on_code() -> None:
    # GIVEN
    markdown = 'First\n**`bold code`** [`linked code`](https://example.com)'

    # WHEN
    document = markdown_to_adf(markdown)

    # THEN ADF takes no other mark on code
    assert document == {'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': 'First'},
        {'type': 'hardBreak'},
        {'type': 'text', 'text': 'bold code', 'marks': [{'type': 'code'}]},
        {'type': 'text', 'text': ' '},
        {'type': 'text', 'text': 'linked code', 'marks': [
            {'type': 'link', 'attrs': {'href': 'https://example.com'}}, {'type': 'code'},
        ]},
    ]}]}
