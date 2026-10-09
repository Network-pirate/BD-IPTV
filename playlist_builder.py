#!/usr/bin/env python3
"""Build a Bangladesh-first, favorites-second M3U playlist from IPTV-org.

Sections:
  1. Bangladesh-origin entries, prioritizing the official Bangladesh playlist,
     and using tvg-id country suffix `.bd` to avoid treating Indian/UK channels
     as Bangladesh-origin merely because they appear in countries/bd.m3u.
  2. User-selected favorites, in favorites.csv order. Matching is deliberately
     conservative: exact tvg-id, or exact title after removing quality/status
     labels. It never moves a channel based on a substring guess.
  3. Every remaining entry from the master playlist, retained in source order.

The generator preserves source entry blocks and numbers all output entries in
sequence with tvg-chno. No stream availability is guaranteed by this tool.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
MASTER_URL = "https://iptv-org.github.io/iptv/index.m3u"
BANGLADESH_URL = "https://iptv-org.github.io/iptv/countries/bd.m3u"
DEFAULT_FAVORITES = ROOT / "favorites.csv"
DEFAULT_OUTPUT = ROOT / "playlist.m3u"
DEFAULT_REPORT = ROOT / "playlist-report.txt"
MIN_ENTRIES = 100
USER_AGENT = "BD-IPTV-PlaylistBuilder/2.1"

ATTR_RE = re.compile(r'''(?<![\w-])(?P<key>[A-Za-z0-9_-]+)\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\s,]+))''')
CHNO_RE = re.compile(r'''(?i)(?<![\w-])tvg-chno\s*=\s*(?:"[^"]*"|'[^']*'|[^\s,]+)''')
RESOLUTION_RE = re.compile(r"\s*\((?:\d{3,4}p|\d{3,4}i)\)", re.I)
STATUS_RE = re.compile(r"\s*\[(?:geo-blocked|not 24/7|no epg|timeshift)\]", re.I)
NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
BD_ID_RE = re.compile(r"\.bd(?:@|$)", re.I)


@dataclass
class Entry:
    lines: list[str]
    original_index: int

    @property
    def extinf(self) -> str:
        return next((line for line in self.lines if line.startswith("#EXTINF:")), "")

    @property
    def attributes(self) -> dict[str, str]:
        head = self.extinf.partition(",")[0]
        values: dict[str, str] = {}
        for match in ATTR_RE.finditer(head):
            value = match.group("double")
            if value is None:
                value = match.group("single")
            if value is None:
                value = match.group("bare")
            values[match.group("key").lower()] = value or ""
        return values

    @property
    def channel_id(self) -> str:
        return self.attributes.get("tvg-id", "").strip()

    @property
    def title(self) -> str:
        return self.extinf.partition(",")[2].strip() or "(untitled entry)"

    @property
    def stream_url(self) -> str:
        return next((line.strip() for line in self.lines if line.strip() and not line.strip().startswith("#")), "")

    @property
    def identity(self) -> str:
        # Keep @SD and @HD distinct: favorites like Star Gold and Star Gold HD
        # must be independently selectable.
        if self.channel_id:
            return "id:" + self.channel_id.casefold()
        if self.stream_url:
            return "url:" + self.stream_url.casefold()
        return "title:" + normalized_title(self.title)

    @property
    def is_bangladesh_origin(self) -> bool:
        return bool(BD_ID_RE.search(self.channel_id))

    def numbered(self, number: int) -> "Entry":
        copy = list(self.lines)
        for i, line in enumerate(copy):
            if not line.startswith("#EXTINF:"):
                continue
            head, comma, title = line.partition(",")
            if CHNO_RE.search(head):
                head = CHNO_RE.sub(f'tvg-chno="{number}"', head, count=1)
            else:
                head = head.rstrip() + f' tvg-chno="{number}"'
            copy[i] = head + (comma + title if comma else "")
            break
        return Entry(copy, self.original_index)


@dataclass
class Favorite:
    order: int
    channel_name: str
    channel_id: str = ""


def normalized_title(title: str) -> str:
    """Normalize display text after removing technical suffix labels only."""
    cleaned = title
    previous = None
    # Resolution and status annotations can appear in either order.
    while cleaned != previous:
        previous = cleaned
        cleaned = RESOLUTION_RE.sub("", cleaned)
        cleaned = STATUS_RE.sub("", cleaned)
    return NORMALIZE_RE.sub("", cleaned.casefold())


def parse_m3u(text: str) -> tuple[list[str], list[Entry]]:
    text = text.lstrip("\ufeff")
    preamble: list[str] = []
    entries: list[Entry] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            if current is not None:
                entries.append(Entry(current, len(entries)))
            current = [line]
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    if current is not None:
        entries.append(Entry(current, len(entries)))
    if not any(line.strip().startswith("#EXTM3U") for line in preamble[:3]):
        raise ValueError("Source does not begin with a valid #EXTM3U header.")
    if not entries:
        raise ValueError("Playlist contains no #EXTINF channel entries.")
    return preamble, entries


def render_m3u(preamble: Iterable[str], entries: Iterable[Entry]) -> str:
    out = list(preamble)
    for entry in entries:
        out.extend(entry.lines)
    return "\n".join(out).rstrip() + "\n"


def fetch_text(url: str, timeout: int = 90) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                raise RuntimeError(f"Source returned HTTP {response.status}: {url}")
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not download {url}: {exc}") from exc
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Source is not valid UTF-8: {url}") from exc


def load_favorites(path: Path) -> list[Favorite]:
    if not path.exists():
        raise RuntimeError(f"Favorites file not found: {path}")
    result: list[Favorite] = []
    seen_order: set[int] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        needed = {"order", "channel_name", "channel_id"}
        if not reader.fieldnames or not needed.issubset(reader.fieldnames):
            raise RuntimeError(f"{path.name} must contain: order,channel_name,channel_id")
        for line_no, row in enumerate(reader, start=2):
            order_text = (row.get("order") or "").strip()
            name = (row.get("channel_name") or "").strip()
            cid = (row.get("channel_id") or "").strip()
            if not order_text and not name and not cid:
                continue
            if not order_text:
                raise RuntimeError(f"{path.name}:{line_no}: order is missing")
            try:
                order = int(order_text)
            except ValueError as exc:
                raise RuntimeError(f"{path.name}:{line_no}: order must be an integer") from exc
            if order < 1:
                raise RuntimeError(f"{path.name}:{line_no}: order must be 1 or higher")
            if order in seen_order:
                raise RuntimeError(f"Favorite order {order} is duplicated")
            if not name and not cid:
                continue
            result.append(Favorite(order, name or cid, cid))
            seen_order.add(order)
    return sorted(result, key=lambda f: f.order)


def same_channel(left: Entry, right: Entry) -> bool:
    # Use exact IDs, preserving distinct SD/HD IDs. URLs provide a fallback
    # when a country playlist entry has no tvg-id.
    if left.channel_id and right.channel_id and left.channel_id.casefold() == right.channel_id.casefold():
        return True
    return bool(left.stream_url and right.stream_url and left.stream_url.casefold() == right.stream_url.casefold())


def match_favorite(favorite: Favorite, entries: list[Entry]) -> tuple[Entry | None, str]:
    if favorite.channel_id:
        hits = [e for e in entries if e.channel_id.casefold() == favorite.channel_id.casefold()]
        if hits:
            return hits[0], "exact tvg-id"
        return None, "tvg-id not found"

    wanted = normalized_title(favorite.channel_name)
    if not wanted:
        return None, "empty channel name"
    exact = [e for e in entries if normalized_title(e.title) == wanted]
    unique: dict[str, Entry] = {}
    for entry in exact:
        unique.setdefault(entry.identity, entry)
    if len(unique) == 1:
        return next(iter(unique.values())), "exact title (quality/status labels ignored)"
    if len(unique) > 1:
        options = sorted({e.title for e in unique.values()})
        return None, "ambiguous exact title: " + "; ".join(options[:8])
    return None, "no exact title or tvg-id match; enter the exact tvg-id instead of guessing"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def build_playlist(master_text: str, favorites: list[Favorite], bd_text: str | None,
                   previous_text: str | None = None, min_entries: int = MIN_ENTRIES
                   ) -> tuple[str, dict[str, object]]:
    preamble, master = parse_m3u(master_text)
    if len(master) < min_entries:
        raise ValueError(f"Safety check: master has {len(master)} entries; expected at least {min_entries}.")
    bd_entries: list[Entry] = []
    if bd_text:
        _, bd_entries = parse_m3u(bd_text)

    # Bangladesh block is based on IDs explicitly tagged with .bd. Entries in
    # the country playlist marked .in/.uk/.ca stay in the later sections.
    bangladesh: list[Entry] = []
    used_master: set[int] = set()
    for bd_entry in bd_entries:
        # Explicit non-BD country IDs should never be promoted to Bangladesh.
        if bd_entry.channel_id and not bd_entry.is_bangladesh_origin:
            continue
        found = next((entry for entry in master
                      if id(entry) not in used_master
                      and entry.is_bangladesh_origin
                      and same_channel(entry, bd_entry)), None)
        if found is not None:
            bangladesh.append(found)
            used_master.add(id(found))
        elif not bd_entry.channel_id or bd_entry.is_bangladesh_origin:
            if not any(same_channel(existing, bd_entry) for existing in bangladesh):
                bangladesh.append(bd_entry)

    # Add every other .bd master entry not enumerated by the country playlist.
    # Do not skip another master entry merely because it shares a tvg-id: the
    # master source entry itself must be preserved (including alternate feeds).
    for entry in master:
        if entry.is_bangladesh_origin and id(entry) not in used_master:
            bangladesh.append(entry)
            used_master.add(id(entry))

    bd_ids = {entry.identity for entry in bangladesh}
    bd_object_ids = {id(entry) for entry in bangladesh}
    rest = [entry for entry in master if id(entry) not in used_master]

    previous: list[Entry] = []
    if previous_text:
        try:
            _, previous = parse_m3u(previous_text)
        except ValueError:
            previous = []

    # Favorites match against all current master entries and BD-only supplements.
    candidates = master + [e for e in bangladesh if id(e) not in {id(m) for m in master}]
    favorite_block: list[Entry] = []
    favorite_ids: set[str] = set()
    resolved: list[str] = []
    already_bd: list[str] = []
    unresolved: list[str] = []
    stale_kept = 0

    for favorite in favorites:
        entry, reason = match_favorite(favorite, candidates)
        from_previous = False
        if entry is None:
            # A prior entry is only allowed as a fallback when the user supplied
            # an exact ID. Never use name-only fuzzy matching on stale data.
            if favorite.channel_id:
                entry, reason = match_favorite(favorite, previous)
                if entry is not None:
                    reason = "retained from previous output; stream may be stale"
                    from_previous = True
            if entry is None:
                unresolved.append(f"{favorite.order}. {favorite.channel_name}: {reason}")
                continue

        if entry.identity in bd_ids or id(entry) in bd_object_ids:
            already_bd.append(f"{favorite.order}. {favorite.channel_name}: already in Bangladesh section")
            continue
        if entry.identity in favorite_ids:
            unresolved.append(f"{favorite.order}. {favorite.channel_name}: duplicate of an earlier favorite")
            continue

        favorite_block.append(entry)
        favorite_ids.add(entry.identity)
        if from_previous:
            stale_kept += 1
        resolved.append(f"{favorite.order}. {favorite.channel_name} -> {entry.title} ({reason})")
        if not from_previous:
            rest = [candidate for candidate in rest if id(candidate) != id(entry)]

    ordered = bangladesh + favorite_block + rest
    numbered = [entry.numbered(index) for index, entry in enumerate(ordered, start=1)]
    output = render_m3u(preamble, numbered)
    _, final_entries = parse_m3u(output)

    master_object_ids = {id(entry) for entry in master}
    extras = sum(1 for entry in bangladesh if id(entry) not in master_object_ids)
    expected = len(master) + extras + stale_kept
    if len(final_entries) != expected:
        raise RuntimeError(f"Entry-count check failed: expected {expected}, got {len(final_entries)}")

    report: dict[str, object] = {
        "master_entries": len(master),
        "bangladesh_entries": len(bangladesh),
        "favorites_placed": len(favorite_block),
        "remaining_entries": len(rest),
        "output_entries": len(final_entries),
        "entries_without_id": sum(1 for entry in master if not entry.channel_id),
        "stale_kept": stale_kept,
        "resolved": resolved,
        "already_bangladesh": already_bd,
        "unresolved": unresolved,
    }
    return output, report


def report_text(r: dict[str, object]) -> str:
    lines = [
        "BD-IPTV Playlist Builder — build report", "",
        f"Master source entries: {r['master_entries']}",
        f"Bangladesh-origin section entries: {r['bangladesh_entries']}",
        f"Favorites placed after Bangladesh: {r['favorites_placed']}",
        f"Remaining master entries: {r['remaining_entries']}",
        f"Total output entries: {r['output_entries']}",
        f"Master entries without tvg-id: {r['entries_without_id']}",
        f"Favorites retained from previous output (possibly stale): {r['stale_kept']}",
        "", "Resolved favorites:",
    ]
    lines.extend(["  " + line for line in r["resolved"]] or ["  (none)"])
    lines += ["", "Favorites already in Bangladesh-origin section:"]
    lines.extend(["  " + line for line in r["already_bangladesh"]] or ["  (none)"])
    lines += ["", "Unresolved favorites (entries remain elsewhere in playlist):"]
    lines.extend(["  " + line for line in r["unresolved"]] or ["  (none)"])
    return "\n".join(lines) + "\n"


def load_source(url: str, local_file: str | None) -> str:
    if local_file:
        try:
            return Path(local_file).read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise RuntimeError(f"Cannot read local source {local_file}: {exc}") from exc
    return fetch_text(url)


def cmd_build(args: argparse.Namespace) -> int:
    favorites = load_favorites(Path(args.favorites))
    master_text = load_source(args.source_url, args.source_file)
    if args.bangladesh_source_file:
        bd_text = load_source(args.bangladesh_source_url, args.bangladesh_source_file)
    elif args.source_file and not args.use_live_bangladesh_source:
        bd_text = None
    else:
        bd_text = fetch_text(args.bangladesh_source_url)

    output_path = Path(args.output)
    previous_text = output_path.read_text(encoding="utf-8-sig") if output_path.exists() else None
    content, report = build_playlist(master_text, favorites, bd_text, previous_text, args.min_entries)
    atomic_write(output_path, content)
    atomic_write(Path(args.report), report_text(report))
    print(f"[OK] Wrote {output_path}")
    print(f"[OK] Wrote {args.report}")
    print(f"     Master source entries:       {report['master_entries']}")
    print(f"     Bangladesh-origin section:  {report['bangladesh_entries']}")
    print(f"     Favorites placed after BD:  {report['favorites_placed']}")
    print(f"     Remaining master entries:   {report['remaining_entries']}")
    print(f"     Total output entries:       {report['output_entries']}")
    if report["unresolved"]:
        print(f"[WARN] {len(report['unresolved'])} favorite(s) were not matched exactly. See playlist-report.txt.")
    if report["stale_kept"]:
        print(f"[WARN] Retained {report['stale_kept']} prior favorite entry/entries; URLs may be stale.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    _, entries = parse_m3u(fetch_text(args.source_url))
    query = args.query.casefold().strip()
    matches = [e for e in entries if query in e.title.casefold() or query in e.channel_id.casefold()]
    if not matches:
        print("No matches. Try a shorter name fragment.")
        return 1
    print(f"Matches: {len(matches)} (showing up to {args.limit})\n")
    for entry in matches[:args.limit]:
        attrs = entry.attributes
        print(f"Name:      {entry.title}")
        print(f"tvg-id:    {entry.channel_id or '(none)'}")
        print(f"Category:  {attrs.get('group-title') or '(not supplied)'}")
        if attrs.get("tvg-logo"):
            print(f"Logo:      {attrs['tvg-logo']}")
        print("-" * 60)
    if len(matches) > args.limit:
        print(f"\n{len(matches) - args.limit} more matches not shown; use --limit.")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bangladesh-first, favorites-second IPTV-org M3U builder")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="Build playlist.m3u and playlist-report.txt")
    b.add_argument("--source-url", default=os.environ.get("IPTV_SOURCE_URL", MASTER_URL))
    b.add_argument("--source-file", help="Use a local master M3U file")
    b.add_argument("--bangladesh-source-url", default=BANGLADESH_URL)
    b.add_argument("--bangladesh-source-file", help="Use a local Bangladesh playlist")
    b.add_argument("--use-live-bangladesh-source", action="store_true", help="Fetch live BD playlist even when master is local")
    b.add_argument("--favorites", default=str(DEFAULT_FAVORITES))
    b.add_argument("--output", default=str(DEFAULT_OUTPUT))
    b.add_argument("--report", default=str(DEFAULT_REPORT))
    b.add_argument("--min-entries", type=int, default=MIN_ENTRIES)
    b.set_defaults(func=cmd_build)
    s = sub.add_parser("search", help="Search master playlist for exact tvg-id values")
    s.add_argument("query")
    s.add_argument("--source-url", default=os.environ.get("IPTV_SOURCE_URL", MASTER_URL))
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_search)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError, csv.Error) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
