"""Compact DOM extraction for VLM consumption.

Playwright is heavyweight: a full DOM dump from a real page can be hundreds of
thousands of tokens. The extractor walks visible interactive elements only,
emitting a markdown table that the VLM can reason about in a few hundred
tokens. The same extractor produces a stable hash so we can detect "no real
change" and short-circuit the next inference call.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

INTERACTIVE_TAGS = ("a", "button", "input", "select", "textarea", "label", "summary")
TEXT_CONTAINER_TAGS = ("h1", "h2", "h3", "h4", "p", "li", "td", "span", "div")


@dataclass
class DOMElement:
    tag: str
    text: str = ""
    selector: str = ""
    attrs: dict[str, str] = field(default_factory = dict)
    visible: bool = True

    def asMarkdownRow(self) -> str:
        text = (self.text or "").strip().replace("\n", " ")
        text = re.sub(r"\s+", " ", text)[:120]
        attrs = " ".join(f'{k}="{v}"' for k, v in self.attrs.items() if v)
        attrSegment = f" [{attrs}]" if attrs else ""
        return f"- {self.tag}{attrSegment}  selector=`{self.selector}`  text=`{text}`"


@dataclass
class DOMState:
    url: str = ""
    title: str = ""
    elements: list[DOMElement] = field(default_factory = list)
    markdown: str = ""
    elementCount: int = 0
    _cachedHash: str = ""

    @property
    def domHash(self) -> str:
        if self._cachedHash:
            return self._cachedHash
        digest = hashlib.sha256()
        digest.update(self.url.encode("utf-8"))
        digest.update(self.markdown.encode("utf-8"))
        object.__setattr__(self, "_cachedHash", digest.hexdigest()[:16])
        return self._cachedHash


async def extractDomState(page: Any, *, maxElements: int = 60) -> DOMState:
    """Walk the live Playwright page and emit a compact DOMState.

    The function is async because Playwright's locator queries are awaitables,
    but it is safe to call against a synchronous test double whose methods
    return plain values (the extractor checks `inspect.isawaitable`).
    """
    import inspect

    async def _maybe(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    url = await _maybe(page.url) if callable(getattr(page, "url", None)) else getattr(page, "url", "")
    title = await _maybe(page.title()) if hasattr(page, "title") else ""

    elements: list[DOMElement] = []
    selector = ", ".join(INTERACTIVE_TAGS) + ", " + ", ".join(TEXT_CONTAINER_TAGS)
    locators = await _maybe(page.locator(selector).all())

    for loc in locators[:maxElements]:
        element = await _buildElement(loc)
        if element is not None and element.text.strip():
            elements.append(element)

    state = DOMState(
        url = url or "",
        title = title or "",
        elements = elements,
        elementCount = len(elements),
    )
    state.markdown = formatDomAsMarkdown(state)
    return state


async def _buildElement(loc: Any) -> DOMElement | None:
    import inspect

    async def _maybe(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    try:
        tag = (await _maybe(loc.evaluate("el => el.tagName.toLowerCase()"))) or ""
    except Exception:
        return None
    visible = True
    try:
        visible = bool(await _maybe(loc.is_visible()))
    except Exception:
        visible = True
    if not visible:
        return None

    text = ""
    try:
        text = (await _maybe(loc.inner_text())) or ""
    except Exception:
        text = ""

    attrs: dict[str, str] = {}
    for name in ("name", "id", "type", "placeholder", "aria-label", "role", "href"):
        try:
            value = await _maybe(loc.get_attribute(name))
        except Exception:
            value = None
        if value:
            attrs[name] = str(value)[:80]

    selector = _buildStableSelector(tag, attrs)
    return DOMElement(tag = tag, text = text, selector = selector, attrs = attrs)


def _buildStableSelector(tag: str, attrs: dict[str, str]) -> str:
    if "id" in attrs:
        return f"#{attrs['id']}"
    if "name" in attrs:
        return f'{tag}[name="{attrs["name"]}"]'
    if "aria-label" in attrs:
        return f'{tag}[aria-label="{attrs["aria-label"]}"]'
    if "placeholder" in attrs:
        return f'{tag}[placeholder="{attrs["placeholder"]}"]'
    return tag


def formatDomAsMarkdown(state: DOMState) -> str:
    lines = [f"# {state.title or 'page'}", f"_url: {state.url}_", ""]
    if not state.elements:
        lines.append("(no interactive elements visible)")
        return "\n".join(lines)
    lines.append(f"## Elements ({state.elementCount})")
    for element in state.elements:
        lines.append(element.asMarkdownRow())
    return "\n".join(lines)


def estimateTokens(text: str) -> int:
    """Rough 4-char-per-token estimate. Good enough for budget guards."""
    if not text:
        return 0
    return max(1, len(text) // 4)
