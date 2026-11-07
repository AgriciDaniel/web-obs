"""Keep content that a page places after its closing </body> or </html> tag.

Browsers move such content into the body and show it. Not every parser does: on GitHub's Windows
runner, lxml 6.1.3 with its bundled libxml2 2.11.9 dropped the links and images after </html>, while
the Linux runner (libxml2 2.14.6) kept them. Moving the real closing tags to the end gives every
parser the browser's reading.

Only real tags count. Closing tag text inside a comment, an attribute value, a script, a style, a
title, a textarea or a template is left alone, and so is a page whose only content after its closers
is whitespace or comments.
"""
from __future__ import annotations

import re

# Elements whose content is text up to their own end tag, as in the HTML standard's tokenizer.
_RAW_TEXT = frozenset({'script', 'style', 'title', 'textarea', 'xmp', 'iframe', 'noembed',
                       'noframes', 'noscript'})
_FOREIGN = frozenset({'svg', 'math'})  # inside these, script, style and title are ordinary elements
_SPACE_CHARS = ' \t\n\r\f'  # HTML whitespace; a no-break space is content
_SPACE = re.compile(r'[ \t\n\r\f]*')
_CLOSER_TEXT = re.compile(r'</(?:body|html)', re.I)
_COMMENT_END = re.compile(r'--!?>')
_TAG_NAME = re.compile(r'[A-Za-z][^ \t\n\r\f/>]*')


def _comment_end(html: str, i: int) -> int:
    """The index just past the comment that starts with '<!--' at i, read as a browser reads it."""
    for opener in ('<!-->', '<!--->'):
        if html.startswith(opener, i):
            return i + len(opener)
    close = _COMMENT_END.search(html, i + 4)
    return len(html) if not close else close.end()


def _tag_end(html: str, i: int) -> int:
    """The index just past the '>' that ends the tag at i. Only a value can be quoted."""
    n = len(html)
    state = 'attributes'
    while i < n:
        c = html[i]
        if c == '>':
            return i + 1
        if state == 'value':
            if c in '"\'':
                close = html.find(c, i + 1)
                if close < 0:
                    return n
                i, state = close + 1, 'attributes'
                continue
            if c not in _SPACE_CHARS:
                state = 'unquoted'
        elif state == 'unquoted':
            if c in _SPACE_CHARS:
                state = 'attributes'
        elif c == '=':
            state = 'value'
        i += 1
    return n


def _real_closers(html: str) -> list[tuple[int, int]]:
    """Spans of the closing body and html tags a browser would see, outside templates."""
    spans: list[tuple[int, int]] = []
    template_depth = foreign_depth = 0
    i, n = 0, len(html)
    while True:
        i = html.find('<', i)
        if i < 0 or i + 1 >= n:
            return spans
        if html.startswith('<!--', i):
            i = _comment_end(html, i)
            continue
        if foreign_depth and html.startswith('<![CDATA[', i):
            close = html.find(']]>', i + 9)
            i = n if close < 0 else close + 3
            continue
        if html[i + 1] in '!?':
            close = html.find('>', i + 2)  # a doctype or a bogus comment ends at the first '>'
            i = n if close < 0 else close + 1
            continue
        closing = html[i + 1] == '/'
        name = _TAG_NAME.match(html, i + 2 if closing else i + 1)
        if not name:
            i += 1
            continue
        tag = name.group().lower()
        end = _tag_end(html, name.end())
        self_closing = html[end - 2:end] == '/>'
        if closing:
            if tag == 'template':
                template_depth = max(0, template_depth - 1)
            elif tag in _FOREIGN:
                foreign_depth = max(0, foreign_depth - 1)
            elif tag in ('body', 'html') and not template_depth:
                spans.append((i, end))
        elif tag == 'template':
            template_depth += 1
        elif tag in _FOREIGN:
            foreign_depth += not self_closing
        elif foreign_depth:
            pass
        elif tag == 'plaintext':
            return spans
        elif tag in _RAW_TEXT:
            close = re.compile(r'</' + re.escape(tag) + r'(?=[ \t\n\r\f/>])', re.I).search(html, end)
            end = n if not close else _tag_end(html, close.end())
        i = end


def _only_comments(text: str) -> bool:
    i, n = _SPACE.match(text).end(), len(text)
    while i < n:
        if not text.startswith('<!--', i):
            return False
        i = _SPACE.match(text, _comment_end(text, i)).end()
    return True


def _without_closer_text(text: str) -> str:
    """Text with every closing body or html tag removed, read as plain text. Linear time."""
    pieces, last = [], 0
    for match in _CLOSER_TEXT.finditer(text):
        if match.start() < last:
            continue
        following = text[match.end():match.end() + 1]
        if following and following not in _SPACE_CHARS + '/>':
            continue
        close = text.find('>', match.end())
        if close < 0:
            break
        pieces.append(text[last:match.start()])
        last = close + 1
    pieces.append(text[last:])
    return ''.join(pieces)


def keep_trailing_content(html):
    """The page with content after its real closing body or html tag moved inside the body.

    Anything other than text is returned unchanged, as is a page with nothing but whitespace or
    comments after its closing tags.
    """
    if not isinstance(html, str):
        return html
    first = _CLOSER_TEXT.search(html)
    # Quick answer for most pages: nothing but closers, whitespace and comments after the first
    # closer text means nothing but that after the real closers either.
    if not first or _only_comments(_without_closer_text(html[first.start():])):
        return html
    spans = _real_closers(html)
    if not spans:
        return html
    pieces, last = [], spans[0][0]
    for start, end in spans:
        pieces.append(html[last:start])
        last = end
    pieces.append(html[last:])
    tail = ''.join(pieces)
    if _only_comments(tail):
        return html
    return html[:spans[0][0]] + tail + '</body></html>'
