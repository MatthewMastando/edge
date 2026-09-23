"""HTML to text. Scripts and styles are dropped; the result is truncated."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP = {"script", "style", "noscript"}
_BREAK = {"p", "div", "br", "li", "h1", "h2", "h3", "tr", "section"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._in_title = False
        self.parts: list[str] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        self.parts.append(data)


def html_to_text(raw: str, *, limit: int) -> tuple[str | None, str, bool]:
    parser = _Extractor()
    parser.feed(raw)
    parser.close()
    title = " ".join(part.strip() for part in parser.title_parts if part.strip()) or None
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts))
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    truncated = len(text) > limit
    return title, text[:limit], truncated
