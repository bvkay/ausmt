"""Shared helpers for the Usage page tests: fetch the page through its route and cut it into its
sections, so a test asserts on the section a rule belongs to rather than on the whole page."""
from __future__ import annotations

import html as _html
import json
import re
from html.parser import HTMLParser

from gateway import serve_state
from gateway.tests.conftest import app_client, curator_login

ROUTE = "/gateway/curator/analytics"

# Section markers in page order. Each section runs from its marker to the next one present.
_MARKERS = (("header", '<div class="u-top">'), ("tiles", '<div class="u-tiles">'),
            ("sofar", '<p class="u-sofar">'), ("who", '<div class="u-card u-who">'),
            ("days", "<h2>Day by day"), ("months", "<h2>Month by month</h2>"),
            ("where", "<h2>What and where"), ("notes", '<div class="u-card u-notes">'))


def write_stats(cfg, doc) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.state_dir / serve_state.STATS_FILENAME
    if doc is None:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps(doc), encoding="utf-8")


async def fetch(tmp_path, doc) -> str:
    """The page as the route renders it for `doc` (None means no stats file)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    async with app_client(tmp_path) as (client, _app, _gw, cfg):
        await curator_login(client)
        write_stats(cfg, doc)
        r = await client.get(ROUTE)
        assert r.status_code == 200, r.status_code
        return r.text


def sections(page: str) -> dict[str, str]:
    """{name: html} for every section present, in page order."""
    found = sorted((page.index(marker), name) for name, marker in _MARKERS if marker in page)
    out = {}
    for i, (start, name) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(page)
        out[name] = page[start:end]
    if "header" in out:
        out["header"] = out["header"].split("</div>", 1)[0] + "</div>"
    return out


def text(fragment: str) -> str:
    """The reader-visible text of a fragment: tags dropped, entities decoded, white space collapsed."""
    plain = _html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", plain).replace(" .", ".").replace(" ,", ",").strip()


def card(page: str, title: str) -> str:
    """One card of the what and where grid, by its heading."""
    where = sections(page)["where"]
    start = where.index(f"<h3>{title}</h3>")
    nxt = where.find('<div class="u-card">', start)
    return where[start:nxt if nxt != -1 else len(where)]


def row_values(fragment: str) -> list[tuple[str, str]]:
    """(name, value) for every ranked row in a card fragment."""
    rows = re.findall(r'<div class="u-rk[^"]*"><span class="u-rk-n">(.*?)</span>(?:<span[^>]*>.*?'
                      r'</span>|<span></span>)<span class="u-rk-v">(.*?)</span></div>', fragment)
    return [(text(name), text(value)) for name, value in rows]


def table_rows(fragment: str) -> list[list[str]]:
    """The cell texts of every body row of the first table in `fragment`, header cell first."""
    body = fragment.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [[text(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S)]


def table_head(fragment: str) -> list[str]:
    head = fragment.split("<thead>", 1)[1].split("</thead>", 1)[0]
    return [text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", head, re.S)]


def tile(page: str, label: str) -> str:
    tiles = sections(page)["tiles"]
    start = tiles.index(f'<div class="u-t-l">{label}</div>')
    nxt = tiles.find('<div class="u-tile', start)
    return tiles[start:nxt if nxt != -1 else len(tiles)]


class Tree(HTMLParser):
    """Every element with its tag, attributes, parent index and direct text, for structural tests."""

    def __init__(self, page: str):
        super().__init__(convert_charrefs=True)
        self.els: list[dict] = []
        self._stack: list[int] = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        parent = self._stack[-1] if self._stack else None
        self.els.append({"tag": tag, "attrs": dict(attrs), "parent": parent, "text": ""})
        self._stack.append(len(self.els) - 1)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self._stack.pop()

    def handle_endtag(self, tag):
        while self._stack:
            if self.els[self._stack.pop()]["tag"] == tag:
                break

    def handle_data(self, data):
        if self._stack:
            self.els[self._stack[-1]]["text"] += data

    def classes(self, i: int) -> set[str]:
        return set((self.els[i]["attrs"].get("class") or "").split())

    def ancestors(self, i: int):
        parent = self.els[i]["parent"]
        while parent is not None:
            yield parent
            parent = self.els[parent]["parent"]

    def find(self, tag: str, cls: str | None = None) -> list[int]:
        return [i for i, e in enumerate(self.els) if e["tag"] == tag
                and (cls is None or cls in self.classes(i))]
