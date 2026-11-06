"""Keep content that a page places after its closing </body> or </html> tag.

Browsers move such content into the body and show it. libxml2 before 2.14 drops it when lxml parses
the page: the lxml wheels for Windows bundle libxml2 2.11, so on Windows a link, image or text after
</html> was missing from the capture. Moving the closing tags to the end gives every parser the
browser's reading.
"""
from __future__ import annotations

import re

_CLOSER = re.compile(r"</(?:body|html)\s*>", re.I)


def keep_trailing_content(html: str) -> str:
    """The page with any content after its first closing body or html tag moved inside the body."""
    if not html:
        return html
    first = _CLOSER.search(html)
    if not first or not _CLOSER.sub("", html[first.end():]).strip():
        return html
    return html[:first.start()] + _CLOSER.sub("", html[first.start():]) + "</body></html>"
