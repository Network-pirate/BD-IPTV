#!/usr/bin/env python3
"""Build an automatically refreshed, numbered M3U playlist from IPTV-org.

Output order:
  1. All Bangladesh-country playlist channels (in the country's playlist order)
  2. User-selected favorites, in favorites.csv order, excluding items already in #1
  3. Every remaining entry from the IPTV-org master playlist

The generator does not filter master-playlist entries. The Bangladesh list can
add entries not found in the master list, so those channels are not lost either.
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
DEFAULT_SOURCE_URL = "https://iptv-org.github.io/iptv/index.m3u"
DEFAULT_BANGLADESH_URL = "https://iptv-org.github.io/iptv/countries/bd.m3u"
DEFAULT_FAVORITES = ROOT / "favorites.csv"
DEFAULT_OUTPUT = ROOT / "playlist.m3u"
DEFAULT_REPORT = ROOT / "playlist-report.txt"
DEFAULT_MIN_ENTRIES = 100
USER_AGENT = "CustomIPTVPlaylistBuilder/2.0 (+https://github.com/iptv-org/iptv)"

ATTR_RE = re.compile(
    r"(?<![\w-])(?P<key>[A-Za-z0-9_-]+)\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|(?P<bare>[^\s,]+))"
)
CHNO_RE = re.compile(r"(?i)(?<![\w-])tvg-chno\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s,]+)")
NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class Entry:
    lines: list[str]
    original_index: int

    @property
    def extinf(self) -> str:
        for line in self.lines:
            if line.startswith("#EXTINF:"):
                return line
        return ""

    @property
    def attributes(self) -> dict[str, str]:
        head = self.extinf.partition(",")[0]
        result: dict[str, str] = {}
        for match in ATTR_RE.finditer(head):
            value = match.group("double")
            if value is None:
                value = match.group("single")
            if value is None:
                value = match.group("bare")
            result[match.group("key").lower()] = value or ""
        return result

    @property
    def channel_id(self) -> str:
        return self.attributes.get("tvg-id", "").strip()

    @property
    def title(self) -> str:
        return self.extinf.partition(",")[2].strip() or "(untitled entry)"

    @property
    def group(self) -> str:
        return self.attributes.get("group-title", "").strip()

    @property
    def stream_url(self) -> str:
        for line in self.lines:
            candidate = line.strip()
            if candidate and not candidate.startswith("#"):
                return candidate
        return ""

    @property
    def channel_key(self) -> str:
        """Best-effort channel identity key, ignoring feed suffixes such as @HD."""
        channel_id = self.channel_id.strip().casefold()
        if channel_id:
            return "id:" + channel_id.split("@", 1)[0]
        if self.stream_url:
            return "url:" + self.stream_url.strip().casefold()
        return "title:" + normalize(self.title)

    def with_number(self, number: int) -> "Entry":
        """Return a copy with tvg-chno replaced or added on #EXTINF."""
        copied = list(self.lines)
        for index, line in enumerate(copied):
            if not line.startswith("#EXTINF:"):
                continue
            head, comma, title = line.partition(",")
            if CHNO_RE.search(head):
                head = CHNO_RE.sub(f'tvg-chno="{number}"', head, count=1)
            else:
                head = f'{head.rstrip()} tvg-chno="{number}"'
            copied[index] = head + (comma + title if comma else "")
            break
        return Entry(copied, self.original_index)


@dataclass
class Favorite:
    order: int
    channel_name: str
    channel_id: str = ""


def normalize(value: str) -> str:
    return NORMALIZE_RE.sub("", value.casefold())


def parse_m3u(text: str) -> tuple[list[str], list[Entry]]:
    """Split a playlist into its preamble and entries without dropping lines."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    preamble: list[str] = []
    entries: list[Entry] = []
    current: list[str] | None = None

    for line in lines:
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

    if not preamble or not any(line.strip().startswith("#EXTM3U") for line in preamble[:3]):
        raise ValueError("The source does not begin with a valid #EXTM3U header.")
    if not entries:
        raise ValueError("The playlist contains no #EXTINF channel entries.")
    return preamble, entries


def render_m3u(preamble: Iterable[str], entries: Iterable[Entry]) -> str:
    lines = list(preamble)
    for entry in entries:
        lines.extend(entry.lines)
    return "\n".join(lines).rstrip() + "\n"


def fetch_text(url: str, timeout: int = 90) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise RuntimeError(f"Source returned HTTP status {status} for {url}.")
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not download source playlist {url}: {exc}") from exc
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Source playlist {url} was not valid UTF-8.") from exc


def load_favorites(path: Path) -> list[Favorite]:
    """Load ordered channel names and optional exact tvg-id values from CSV."""
    if not path.exists():
        raise RuntimeError(f"Favorites file not found: {path}")

    favorites: list[Favorite] = []
    seen_orders: set[int] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {"order", "channel_name", "channel_id"}
        if not reader.fieldnames or not expected.issubset(set(reader.fieldnames)):
            raise RuntimeError(
                f"{path.name} must have the columns: order,channel_name,channel_id"
            )
        for line_num, row in enumerate(reader, start=2):
            order_text = (row.get("order") or "").strip()
            channel_name = (row.get("channel_name") or "").strip()
            channel_id = (row.get("channel_id") or "").strip()
            if not order_text and not channel_name and not channel_id:
                continue
            if not order_text:
                raise RuntimeError(f"{path.name}:{line_num}: order is missing.")
            try:
                order = int(order_text)
            except ValueError as exc:
                raise RuntimeError(f"{path.name}:{line_num}: order must be an integer.") from exc
            if order < 1:
                raise RuntimeError(f"{path.name}:{line_num}: order must be at least 1.")
            if order in seen_orders:
                raise RuntimeError(f"Favorite order {order} is used more than once.")
            if not channel_name and not channel_id:
                continue
            if not channel_name:
                channel_name = channel_id
            favorites.append(Favorite(order, channel_name, channel_id))
            seen_orders.add(order)
    return sorted(favorites, key=lambda item: item.order)


def entry_identity(entry: Entry) -> str:
    return entry.channel_key


def same_channel(left: Entry, right: Entry) -> bool:
    """Match source entries by canonical tvg-id, falling back to exact stream URL."""
    if left.channel_id and right.channel_id:
        left_base = left.channel_id.casefold().split("@", 1)[0]
        right_base = right.channel_id.casefold().split("@", 1)[0]
        if left_base == right_base:
            return True
    left_url = left.stream_url.strip().casefold()
    right_url = right.stream_url.strip().casefold()
    return bool(left_url and right_url and left_url == right_url)


def entry_matches_channel_id(entry: Entry, channel_id: str) -> bool:
    wanted = channel_id.strip().casefold()
    actual = entry.channel_id.casefold()
    if not wanted or not actual:
        return False
    return actual == wanted or actual.split("@", 1)[0] == wanted.split("@", 1)[0]


def match_favorite(favorite: Favorite, entries: list[Entry]) -> tuple[Entry | None, str]:
    """Resolve a configured favorite by ID, exact title, or unambiguous title fragment."""
    if favorite.channel_id:
        hits = [entry for entry in entries if entry_matches_channel_id(entry, favorite.channel_id)]
        unique: dict[str, Entry] = {}
        for entry in hits:
            unique.setdefault(entry_identity(entry), entry)
        if len(unique) == 1:
            return next(iter(unique.values())), "matched by tvg-id"
        if len(unique) > 1:
            return None, "ambiguous tvg-id match"
        return None, "tvg-id not found"

    query = normalize(favorite.channel_name)
    if not query:
        return None, "empty channel name"

    # Prefer exact title matches.
    exact = [entry for entry in entries if normalize(entry.title) == query]
    unique_exact: dict[str, Entry] = {}
    for entry in exact:
        unique_exact.setdefault(entry_identity(entry), entry)
    if len(unique_exact) == 1:
        return next(iter(unique_exact.values())), "exact title match"
    if len(unique_exact) > 1:
        return None, "ambiguous exact title"

    # A fragment such as "Star Gold 2" may match a title with a quality suffix.
    partial = [
        entry for entry in entries
        if query in normalize(entry.title) or query in normalize(entry.channel_id)
    ]
    unique_partial: dict[str, Entry] = {}
    for entry in partial:
        unique_partial.setdefault(entry_identity(entry), entry)
    if len(unique_partial) == 1:
        return next(iter(unique_partial.values()), None), "unique title fragment"
    if len(unique_partial) > 1:
        titles = sorted({entry.title for entry in unique_partial.values()})
        return None, "ambiguous: " + "; ".join(titles[:8])
    return None, "not found in current source"


def make_playlist(
    source_text: str,
    favorites: list[Favorite],
    bangladesh_text: str | None = None,
    previous_text: str | None = None,
    min_entries: int = DEFAULT_MIN_ENTRIES,
) -> tuple[str, dict[str, object]]:
    preamble, source_entries = parse_m3u(source_text)
    if len(source_entries) < min_entries:
        raise ValueError(
            f"Safety check failed: master source has {len(source_entries)} entries; "
            f"expected at least {min_entries}. The output was not changed. "
            "Use --min-entries only when intentionally testing with a small sample."
        )

    if bangladesh_text:
        _, bangladesh_entries = parse_m3u(bangladesh_text)
    else:
        bangladesh_entries = []

    # Build the Bangladesh block in the country playlist's order, using master
    # entries whenever the same channel exists there. This includes BD entries
    # missing from the master list without dropping any master entry.
    bangladesh_block: list[Entry] = []
    used_master_ids: set[int] = set()
    seen_bangladesh: list[Entry] = []
    for bd_entry in bangladesh_entries:
        seen_bangladesh.append(bd_entry)
        available = next(
            (e for e in source_entries if id(e) not in used_master_ids and same_channel(e, bd_entry)),
            None,
        )
        if available is not None:
            bangladesh_block.append(available)
            used_master_ids.add(id(available))
            continue

        # If the BD entry is already represented in the master source (perhaps
        # by another same-channel entry), it will be added in the pass below.
        exists_in_master = any(same_channel(e, bd_entry) for e in source_entries)
        exists_in_block = any(same_channel(e, bd_entry) for e in bangladesh_block)
        if not exists_in_master and not exists_in_block:
            bangladesh_block.append(bd_entry)

    # Preserve every master entry and move all master entries identified as
    # Bangladesh into the first section. A channel may appear more than once in
    # the source; we preserve those entries rather than filtering them out.
    for entry in source_entries:
        if id(entry) in used_master_ids:
            continue
        if any(same_channel(entry, bd_entry) for bd_entry in bangladesh_entries):
            bangladesh_block.append(entry)
            used_master_ids.add(id(entry))

    # Channel keys already in the first section help avoid duplicating a chosen
    # favorite that is also a Bangladesh channel.
    bd_keys = {entry_identity(entry) for entry in bangladesh_block}

    previous_index: dict[str, Entry] = {}
    if previous_text:
        try:
            _, previous_entries = parse_m3u(previous_text)
            for entry in previous_entries:
                if entry.channel_id:
                    previous_index.setdefault(entry.channel_id.casefold(), entry)
                    previous_index.setdefault(entry.channel_id.casefold().split("@", 1)[0], entry)
        except ValueError:
            previous_index = {}

    # Candidate list holds each source entry once, preferring master versions.
    rest_master = [e for e in source_entries if id(e) not in used_master_ids]
    candidate_entries = bangladesh_block + rest_master
    favorite_block: list[Entry] = []
    used_favorite_keys: set[str] = set()
    unresolved: list[str] = []
    already_in_bangladesh: list[str] = []
    resolved_names: list[str] = []
    stale_fallbacks = 0

    for favorite in favorites:
        matched, reason = match_favorite(favorite, candidate_entries)
        used_stale_fallback = False
        if matched is None and favorite.channel_id:
            old = previous_index.get(favorite.channel_id.casefold()) or previous_index.get(
                favorite.channel_id.casefold().split("@", 1)[0]
            )
            if old is not None:
                matched = old
                reason = "kept from previous playlist; URL may be stale"
                used_stale_fallback = True
        if matched is None:
            unresolved.append(f"{favorite.order}. {favorite.channel_name}: {reason}")
            continue

        key = entry_identity(matched)
        if key in bd_keys or id(matched) in {id(e) for e in bangladesh_block}:
            already_in_bangladesh.append(f"{favorite.order}. {favorite.channel_name}: already placed in Bangladesh section")
            continue
        if key in used_favorite_keys:
            unresolved.append(f"{favorite.order}. {favorite.channel_name}: duplicate of an earlier favorite")
            continue
        # If this is a fresh source entry, remove that exact entry from the rest.
        if id(matched) in {id(e) for e in rest_master}:
            rest_master = [e for e in rest_master if id(e) != id(matched)]
        favorite_block.append(matched)
        used_favorite_keys.add(key)
        if used_stale_fallback:
            stale_fallbacks += 1
        resolved_names.append(f"{favorite.order}. {favorite.channel_name} -> {matched.title} ({reason})")

    # Source entries in the remaining block retain their upstream order.
    ordered_unumbered = bangladesh_block + favorite_block + rest_master
    numbered_entries = [entry.with_number(i) for i, entry in enumerate(ordered_unumbered, start=1)]
    result = render_m3u(preamble, numbered_entries)

    _, final_entries = parse_m3u(result)
    source_object_ids = {id(entry) for entry in source_entries}
    extra_bangladesh_entries = sum(
        1 for entry in bangladesh_block if id(entry) not in source_object_ids
    )
    expected_count = len(source_entries) + extra_bangladesh_entries + stale_fallbacks
    if len(final_entries) != expected_count:
        raise RuntimeError(
            f"Entry-count check failed: expected {expected_count}, got {len(final_entries)}."
        )

    bd_count = len(bangladesh_block)
    fav_count = len(favorite_block)
    report: dict[str, object] = {
        "master_entries": len(source_entries),
        "bangladesh_entries": bd_count,
        "resolved_favorites": fav_count,
        "remaining_entries": len(rest_master),
        "output_entries": len(final_entries),
        "unidentified_entries": sum(1 for entry in source_entries if not entry.channel_id),
        "stale_fallbacks": stale_fallbacks,
        "resolved_names": resolved_names,
        "already_in_bangladesh": already_in_bangladesh,
        "unresolved_favorites": unresolved,
    }
    return result, report


def render_report(report: dict[str, object]) -> str:
    lines = [
        "Custom IPTV Playlist Builder — last build report",
        "",
        f"Master source entries: {report['master_entries']}",
        f"Bangladesh section entries: {report['bangladesh_entries']}",
        f"Favorites placed after Bangladesh: {report['resolved_favorites']}",
        f"Remaining master entries: {report['remaining_entries']}",
        f"Total output entries: {report['output_entries']}",
        f"Entries without tvg-id: {report['unidentified_entries']}",
        f"Favorites retained from previous playlist (possibly stale URLs): {report['stale_fallbacks']}",
        "",
        "Resolved favorites:",
    ]
    lines.extend(["  " + item for item in report["resolved_names"]] or ["  (none)"])
    lines += ["", "Favorites already in the Bangladesh section:"]
    lines.extend(["  " + item for item in report["already_in_bangladesh"]] or ["  (none)"])
    lines += ["", "Unresolved or ambiguous favorites (their source entries are still preserved elsewhere):"]
    lines.extend(["  " + item for item in report["unresolved_favorites"]] or ["  (none)"])
    lines.append("")
    return "\n".join(lines)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def load_source(source_url: str, source_file: Path | None) -> str:
    if source_file:
        try:
            return source_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise RuntimeError(f"Could not read source file {source_file}: {exc}") from exc
    return fetch_text(source_url)


def cmd_build(args: argparse.Namespace) -> int:
    favorites = load_favorites(Path(args.favorites))
    source_text = load_source(args.source_url, Path(args.source_file) if args.source_file else None)
    if args.bangladesh_source_file:
        bangladesh_text = load_source(args.bangladesh_source_url, Path(args.bangladesh_source_file))
    elif args.source_file and not args.bangladesh_source_url_explicit:
        # Local-source/testing mode should not unexpectedly fetch live data.
        bangladesh_text = None
    else:
        bangladesh_text = fetch_text(args.bangladesh_source_url)

    output_path = Path(args.output)
    previous_text = None
    if output_path.exists():
        try:
            previous_text = output_path.read_text(encoding="utf-8-sig")
        except OSError:
            previous_text = None

    playlist, report = make_playlist(
        source_text,
        favorites,
        bangladesh_text=bangladesh_text,
        previous_text=previous_text,
        min_entries=args.min_entries,
    )
    atomic_write(output_path, playlist)
    report_path = Path(args.report)
    atomic_write(report_path, render_report(report))
    print(f"[OK] Wrote {output_path}")
    print(f"[OK] Wrote {report_path}")
    print(f"     Master source entries:       {report['master_entries']}")
    print(f"     Bangladesh section:          {report['bangladesh_entries']}")
    print(f"     Favorites after Bangladesh:  {report['resolved_favorites']}")
    print(f"     Remaining master entries:    {report['remaining_entries']}")
    print(f"     Output entries:              {report['output_entries']}")
    if report["unresolved_favorites"]:
        print(f"[WARN] {len(report['unresolved_favorites'])} favorite(s) were not uniquely resolved.")
        print("       See playlist-report.txt. Their entries are still kept in the playlist.")
    if report["stale_fallbacks"]:
        print(
            f"[WARN] Kept {report['stale_fallbacks']} favorite(s) from the previous playlist "
            "because they were absent upstream. Their URLs may be stale."
        )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    text = fetch_text(args.source_url)
    _, entries = parse_m3u(text)
    query = args.query.casefold().strip()
    matches = [
        entry for entry in entries
        if query in entry.title.casefold() or query in entry.channel_id.casefold()
    ]
    if not matches:
        print("No matching channels found. Try a shorter search term.")
        return 1
    print(f"Matches: {len(matches)} (showing up to {args.limit})\n")
    for entry in matches[: args.limit]:
        attrs = entry.attributes
        print(f"Name:      {entry.title}")
        print(f"tvg-id:    {entry.channel_id or '(none — cannot map by ID)'}")
        print(f"Category:  {entry.group or '(not supplied)'}")
        if attrs.get("tvg-logo"):
            print(f"Logo:      {attrs['tvg-logo']}")
        print("-" * 60)
    if len(matches) > args.limit:
        print(f"\n{len(matches) - args.limit} more matches not shown; use --limit.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a numbered IPTV-org playlist with Bangladesh channels first, then ordered favorites, then all remaining channels."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Generate playlist.m3u and playlist-report.txt")
    build.add_argument("--source-url", default=os.environ.get("IPTV_SOURCE_URL", DEFAULT_SOURCE_URL))
    build.add_argument("--source-file", help="Use a local master M3U file instead of downloading")
    build.add_argument("--bangladesh-source-url", default=DEFAULT_BANGLADESH_URL)
    build.add_argument("--bangladesh-source-file", help="Use a local Bangladesh M3U file")
    # Track whether the Bangladesh URL was explicitly chosen to support the
    # local-source testing behavior above.
    build.add_argument("--favorites", default=str(DEFAULT_FAVORITES))
    build.add_argument("--output", default=str(DEFAULT_OUTPUT))
    build.add_argument("--report", default=str(DEFAULT_REPORT))
    build.add_argument("--min-entries", type=int, default=DEFAULT_MIN_ENTRIES)
    build.set_defaults(func=cmd_build, bangladesh_source_url_explicit=False)

    search = sub.add_parser("search", help="Find a channel and its exact tvg-id")
    search.add_argument("query", help="A channel-name fragment or tvg-id")
    search.add_argument("--source-url", default=os.environ.get("IPTV_SOURCE_URL", DEFAULT_SOURCE_URL))
    search.add_argument("--limit", type=int, default=30)
    search.set_defaults(func=cmd_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # argparse uses the default for this value; detect explicit override from argv.
    if args.command == "build" and argv is not None:
        args.bangladesh_source_url_explicit = "--bangladesh-source-url" in argv
    elif args.command == "build":
        args.bangladesh_source_url_explicit = "--bangladesh-source-url" in sys.argv[1:]
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError, csv.Error) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
