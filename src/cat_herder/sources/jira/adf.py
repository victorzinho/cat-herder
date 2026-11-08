import re
from datetime import UTC, datetime
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

type AdfNode = dict[str, Any]

_INLINE_TYPES = {'text', 'hardBreak', 'mention', 'emoji', 'inlineCard', 'date', 'status', 'mediaInline'}
_MEDIA_TYPES = {'mediaSingle', 'mediaGroup', 'media', 'mediaInline'}
# Code goes innermost: marks around it still apply, while marks inside it would show as literal characters.
_MARK_ORDER = {'code': 0, 'strong': 1, 'em': 2, 'strike': 3, 'link': 4}
_MARKDOWN = MarkdownIt('commonmark').enable(['table', 'strikethrough'])
_MARK_BY_MARKDOWN = {'strong': 'strong', 'em': 'em', 's': 'strike'}


def adf_to_markdown(document: AdfNode) -> str:
    """Render an Atlassian Document Format document as markdown.

    A node with no markdown equivalent renders its content, or its text when it has no content. Media are left out.
    """
    lines = [line.rstrip() for line in _blocks(document.get('content', [])).splitlines()]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def _blocks(nodes: list[AdfNode], separator: str = '\n\n') -> str:
    return separator.join(rendered for node in nodes if (rendered := _block(node)))


def _block(node: AdfNode) -> str:
    content: list[AdfNode] = node.get('content', [])
    attrs: dict[str, Any] = node.get('attrs', {})
    match node['type']:
        case 'paragraph':
            return _inline(content)
        case 'heading':
            return f'{"#" * attrs["level"]} {_inline(content)}'
        case 'bulletList':
            return '\n'.join(_list_item('-', item) for item in content)
        case 'orderedList':
            start = attrs.get('order', 1)
            return '\n'.join(_list_item(f'{start + index}.', item) for index, item in enumerate(content))
        case 'taskList':
            return '\n'.join(_task(child) for child in content)
        case 'codeBlock':
            return f'```{attrs.get("language") or ""}\n{_plain_text(content)}\n```'
        case 'blockquote' | 'panel':
            return '\n'.join(f'> {line}'.rstrip() for line in _blocks(content).splitlines())
        case 'rule':
            return '---'
        case 'table':
            return _table(content)
        case 'expand' | 'nestedExpand' if attrs.get('title'):
            return _blocks([_bold_paragraph(attrs['title']), *content])
        case node_type if node_type in _MEDIA_TYPES:
            return ''
        case node_type if node_type in _INLINE_TYPES:
            return _inline([node])
        case _:
            return _blocks(content) if content else attrs.get('text', '')


def _inline(nodes: list[AdfNode]) -> str:
    return ''.join(_inline_node(node) for node in nodes)


def _inline_node(node: AdfNode) -> str:
    attrs: dict[str, Any] = node.get('attrs', {})
    match node['type']:
        case 'text':
            return _marked(node['text'], node.get('marks', []))
        case 'hardBreak':
            return '\n'
        case 'mention' | 'status':
            return attrs.get('text', '')
        case 'emoji':
            return attrs.get('text') or attrs.get('shortName', '')
        case 'inlineCard':
            return attrs.get('url', '')
        case 'date':
            return datetime.fromtimestamp(int(attrs['timestamp']) / 1000, UTC).date().isoformat()
        case node_type if node_type in _MEDIA_TYPES:
            return ''
        case _:
            return _inline(node['content']) if 'content' in node else attrs.get('text', '')


def _marked(text: str, marks: list[AdfNode]) -> str:
    # Markdown ignores emphasis that starts or ends with a space, so spaces stay outside the marks.
    core = text.strip()
    if not core:
        return text
    for mark in sorted(marks, key=lambda mark: _MARK_ORDER.get(mark['type'], len(_MARK_ORDER))):
        match mark['type']:
            case 'code':
                core = f'`{core}`'
            case 'strong':
                core = f'**{core}**'
            case 'em':
                core = f'_{core}_'
            case 'strike':
                core = f'~~{core}~~'
            case 'link':
                core = f'[{core}]({mark["attrs"]["href"]})'
            case _:
                pass
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    return f'{leading}{core}{trailing}'


def _list_item(marker: str, item: AdfNode) -> str:
    # Nested lists follow their paragraph on the next line: a blank line would make the list loose.
    lines = _blocks(item.get('content', []), separator='\n').splitlines() or ['']
    indent = ' ' * (len(marker) + 1)
    return '\n'.join([f'{marker} {lines[0]}', *(f'{indent}{line}' if line else '' for line in lines[1:])])


def _task(node: AdfNode) -> str:
    if node['type'] == 'taskList':
        return '\n'.join(f'  {line}' for line in _block(node).splitlines())
    checked = 'x' if node.get('attrs', {}).get('state') == 'DONE' else ' '
    return f'- [{checked}] {_inline(node.get("content", []))}'


def _table(rows: list[AdfNode]) -> str:
    rendered = [
        '| ' + ' | '.join(_cell(cell) for cell in row.get('content', [])) + ' |' for row in rows if row.get('content')
    ]
    if not rendered:
        return ''
    columns = len(rows[0]['content'])
    return '\n'.join([rendered[0], '|' + ' --- |' * columns, *rendered[1:]])


def _cell(cell: AdfNode) -> str:
    return _blocks(cell.get('content', []), separator=' ').replace('\n', ' ').replace('|', '\\|')


def _bold_paragraph(text: str) -> AdfNode:
    return {'type': 'paragraph', 'content': [{'type': 'text', 'text': text, 'marks': [{'type': 'strong'}]}]}


def _plain_text(nodes: list[AdfNode]) -> str:
    return ''.join(_plain_text_of(node) for node in nodes)


def _plain_text_of(node: AdfNode) -> str:
    match node['type']:
        case 'text':
            return node.get('text', '')
        case 'hardBreak':
            return '\n'
        case _:
            return _plain_text(node.get('content', []))


def markdown_to_adf(markdown: str) -> AdfNode:
    """Turn markdown into an Atlassian Document Format document, the way adf_to_markdown renders one back.

    Line breaks inside a paragraph are kept, and HTML and images stay as their text.
    """
    return {'type': 'doc', 'version': 1, 'content': _adf_blocks(SyntaxTreeNode(_MARKDOWN.parse(markdown)).children)}


def _adf_blocks(nodes: list[SyntaxTreeNode]) -> list[AdfNode]:
    return [_adf_block(node) for node in nodes]


def _adf_block(node: SyntaxTreeNode) -> AdfNode:
    match node.type:
        case 'paragraph':
            return {'type': 'paragraph', 'content': _adf_inline(node.children[0].children)}
        case 'heading':
            return {'type': 'heading', 'attrs': {'level': int(node.tag[1:])}, 'content': _adf_inline_of(node)}
        case 'bullet_list':
            return {'type': 'bulletList', 'content': _adf_blocks(node.children)}
        case 'ordered_list':
            order = int(str(node.attrs.get('start', 1)))
            return {'type': 'orderedList', 'attrs': {'order': order}, 'content': _adf_blocks(node.children)}
        case 'list_item':
            return {'type': 'listItem', 'content': _adf_blocks(node.children)}
        case 'blockquote':
            return {'type': 'blockquote', 'content': _adf_blocks(node.children)}
        case 'hr':
            return {'type': 'rule'}
        case 'fence' | 'code_block':
            code = node.content.removesuffix('\n')
            return {
                'type': 'codeBlock',
                'attrs': {'language': node.info} if node.info else {},
                'content': [{'type': 'text', 'text': code}] if code else [],
            }
        case 'table':
            rows = [row for section in node.children for row in section.children]
            return {'type': 'table', 'content': [_adf_table_row(row) for row in rows]}
        case _:
            return {'type': 'paragraph', 'content': _adf_text(node.content.strip(), [])}


def _adf_table_row(row: SyntaxTreeNode) -> AdfNode:
    cells = [
        {
            'type': 'tableHeader' if cell.type == 'th' else 'tableCell',
            'content': [{'type': 'paragraph', 'content': _adf_inline_of(cell)}],
        }
        for cell in row.children
    ]
    return {'type': 'tableRow', 'content': cells}


def _adf_inline_of(node: SyntaxTreeNode) -> list[AdfNode]:
    # Headings and table cells hold one inline node, empty when they have no text.
    return _adf_inline(node.children[0].children) if node.children else []


def _adf_inline(nodes: list[SyntaxTreeNode], marks: tuple[AdfNode, ...] = ()) -> list[AdfNode]:
    adf: list[AdfNode] = []
    for node in nodes:
        match node.type:
            case 'softbreak' | 'hardbreak':
                adf.append({'type': 'hardBreak'})
            case 'code_inline':
                # Code can only be a link besides.
                links = [mark for mark in marks if mark['type'] == 'link']
                adf.extend(_adf_text(node.content, [*links, {'type': 'code'}]))
            case 'link':
                link = {'type': 'link', 'attrs': {'href': node.attrs['href']}}
                adf.extend(_adf_inline(node.children, (*marks, link)))
            case markdown_mark if mark := _MARK_BY_MARKDOWN.get(markdown_mark):
                adf.extend(_adf_inline(node.children, (*marks, {'type': mark})))
            case 'image':
                adf.extend(_adf_inline(node.children, marks))
            case _:
                adf.extend(_adf_text(node.content, list(marks)))
    return adf


def _adf_text(text: str, marks: list[AdfNode]) -> list[AdfNode]:
    # ADF has no empty text nodes.
    if not text:
        return []
    return [{'type': 'text', 'text': text, 'marks': marks} if marks else {'type': 'text', 'text': text}]
