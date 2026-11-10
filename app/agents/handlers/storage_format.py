"""Confluence storage-format (XHTML) helpers: validation, escaping, macros."""

import html
import re
from xml.etree import ElementTree

_NAMED_ENTITIES = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)([a-zA-Z]+);")
_WRAPPER = (
    '<root xmlns:ac="http://atlassian.com/content" '
    'xmlns:ri="http://atlassian.com/resource/identifier">{}</root>'
)


def normalise_entities(body: str) -> str:
    """XML only knows 5 named entities; convert the rest (&nbsp; …) to numeric references."""

    def repl(match: re.Match[str]) -> str:
        char = html.unescape(match.group(0))
        return f"&#{ord(char)};" if len(char) == 1 else match.group(0)

    return _NAMED_ENTITIES.sub(repl, body)


def is_well_formed(body: str) -> bool:
    try:
        ElementTree.fromstring(_WRAPPER.format(normalise_entities(body)))  # noqa: S314 - own content
    except ElementTree.ParseError:
        return False
    return True


def text_to_storage(text: str) -> str:
    return "".join(f"<p>{html.escape(p.strip())}</p>" for p in text.split("\n\n") if p.strip())


def jira_issues_macro(jql: str, max_issues: int = 20) -> str:
    return (
        '<ac:structured-macro ac:name="jira" ac:schema-version="1">'
        f'<ac:parameter ac:name="jqlQuery">{html.escape(jql)}</ac:parameter>'
        f'<ac:parameter ac:name="maximumIssues">{max_issues}</ac:parameter>'
        "</ac:structured-macro>"
    )


def children_macro() -> str:
    return (
        '<ac:structured-macro ac:name="children" ac:schema-version="2">'
        '<ac:parameter ac:name="all">true</ac:parameter>'
        "</ac:structured-macro>"
    )
