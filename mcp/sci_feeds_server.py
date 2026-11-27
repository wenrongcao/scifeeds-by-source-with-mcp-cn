"""Local read-only MCP server for the user's SciFeeds OPML subscriptions."""

from __future__ import annotations

import email.utils
import html
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
import sys


BASE_DIR = Path(__file__).resolve().parent
OPML_PATH = BASE_DIR / "feeds.opml"
MAX_FEED_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = 18
USER_AGENT = "SciFeeds-MCP/1.0 (personal RSS reader)"

def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in element:
        if _local_name(child.tag) in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def parse_opml(data: bytes) -> list[dict[str, str]]:
    """Extract RSS/Atom subscriptions from OPML, including nested folders."""
    root = ET.fromstring(data)
    feeds: list[dict[str, str]] = []
    seen: set[str] = set()
    for outline in root.iter():
        if _local_name(outline.tag) != "outline":
            continue
        url = (outline.get("xmlUrl") or outline.get("xmlurl") or "").strip()
        if not url or url in seen:
            continue
        if not url.lower().startswith(("https://", "http://")):
            continue
        seen.add(url)
        title = (outline.get("title") or outline.get("text") or url).strip()
        feeds.append({
            "title": title,
            "url": url,
            "site_url": (outline.get("htmlUrl") or outline.get("htmlurl") or "").strip(),
        })
    return feeds


def load_feeds() -> list[dict[str, str]]:
    return parse_opml(OPML_PATH.read_bytes())


def _parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str, max_chars: int = 1200) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(value)
        text = " ".join(extractor.parts)
    except Exception:
        text = value
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def parse_feed(data: bytes, feed_title: str) -> list[dict[str, Any]]:
    """Parse common RSS 2.x and Atom entries into a uniform shape."""
    root = ET.fromstring(data)
    item_elements = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    entries: list[dict[str, Any]] = []
    for item in item_elements:
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if not link:
            links = [child for child in item if _local_name(child.tag) == "link"]
            alternate = next((child for child in links if child.get("rel", "alternate") == "alternate"), None)
            selected = alternate if alternate is not None else (links[0] if links else None)
            if selected is not None:
                link = (selected.get("href") or "").strip()
        raw_date = _child_text(item, "pubDate", "published", "updated", "date")
        published = _parse_datetime(raw_date)
        summary = _child_text(item, "description", "summary", "content", "encoded")
        entry: dict[str, Any] = {
            "feed_title": feed_title,
            "title": title or "(untitled)",
            "link": link,
            "published": published.isoformat() if published else None,
            "summary": _plain_text(summary),
        }
        entries.append(entry)
    return entries


def _fetch_one(feed: dict[str, str], cutoff: datetime, max_per_feed: int) -> tuple[list[dict[str, Any]], str | None]:
    request = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            data = response.read(MAX_FEED_BYTES + 1)
        if len(data) > MAX_FEED_BYTES:
            return [], "Feed exceeds 2 MiB size limit"
        parsed = parse_feed(data, feed["title"])
    except (urllib.error.URLError, TimeoutError, OSError, ET.ParseError, ValueError) as exc:
        reason = getattr(exc, "reason", None)
        message = str(reason or exc).replace("\n", " ")[:220]
        return [], f"{type(exc).__name__}: {message}"

    fresh: list[dict[str, Any]] = []
    for entry in parsed:
        date_value = entry["published"]
        if not date_value:
            continue
        published = datetime.fromisoformat(date_value)
        if published >= cutoff:
            fresh.append(entry)
    fresh.sort(key=lambda entry: entry["published"] or "", reverse=True)
    return fresh[:max_per_feed], None


def list_feeds() -> list[dict[str, str]]:
    """List all feeds in the local SciFeeds OPML, with feed and website URLs."""
    return load_feeds()


def fetch_recent_entries(days: int = 7, feed_title: str = "", max_per_feed: int = 100) -> dict[str, Any]:
    """Fetch entries published within the last N days from subscribed feeds.

    Optionally restrict to one feed by its title (case-insensitive exact match).
    Entries without a parseable publication date are omitted. Each feed fetch
    is bounded by an 18-second timeout and a 2 MiB response limit.
    """
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")
    if not 1 <= max_per_feed <= 100:
        raise ValueError("max_per_feed must be between 1 and 100")

    feeds = load_feeds()
    if feed_title.strip():
        query = feed_title.strip().casefold()
        feeds = [feed for feed in feeds if feed["title"].casefold() == query]
        if not feeds:
            return {"entries": [], "errors": [f"No feed titled {feed_title!r} was found."]}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_entries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(feeds)))) as pool:
        futures = {pool.submit(_fetch_one, feed, cutoff, max_per_feed): feed for feed in feeds}
        for future in as_completed(futures):
            feed = futures[future]
            try:
                entries, error = future.result()
            except Exception as exc:  # keep one broken feed from failing the batch
                entries, error = [], f"{type(exc).__name__}: {str(exc)[:220]}"
            all_entries.extend(entries)
            if error:
                errors.append({"feed_title": feed["title"], "error": error})
    all_entries.sort(key=lambda entry: entry["published"] or "", reverse=True)
    return {
        "requested_days": days,
        "feed_count": len(feeds),
        "entry_count": len(all_entries),
        "entries": all_entries,
        "errors": errors,
    }


TOOLS = [
    {
        "name": "list_feeds",
        "description": "List RSS/Atom subscriptions from the local SciFeeds OPML file.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "fetch_recent_entries",
        "description": "Fetch recent entries from subscribed feeds. Entries without a parseable publication date are omitted. Each feed request has an 18-second timeout and 2 MiB response cap.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Look-back period, 1-365 days (default 7).", "minimum": 1, "maximum": 365},
                "feed_title": {"type": "string", "description": "Optional exact feed title, case-insensitive."},
                "max_per_feed": {"type": "integer", "description": "Maximum entries per feed, 1-100 (default 100).", "minimum": 1, "maximum": 100, "default": 100},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    },
]

SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}


def _tool_result(value: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
        "structuredContent": value,
        "isError": is_error,
    }


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one MCP JSON-RPC message; return None for notifications."""
    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        if "id" not in message:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid Request"}}

    if "id" not in message:
        return None

    params = message.get("params") or {}
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid params"}}

    if method == "initialize":
        requested = params.get("protocolVersion", "2024-11-05")
        version = requested if requested in SUPPORTED_PROTOCOLS else "2024-11-05"
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "sci-feeds", "version": "1.0.0"},
        }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Tool arguments must be an object"}}
        try:
            if name == "list_feeds":
                feeds = list_feeds()
                value = {"feed_count": len(feeds), "feeds": feeds}
            elif name == "fetch_recent_entries":
                days = arguments.get("days", 7)
                max_per_feed = arguments.get("max_per_feed", 100)
                feed_title = arguments.get("feed_title", "")
                if isinstance(days, bool) or not isinstance(days, int):
                    raise ValueError("days must be an integer")
                if isinstance(max_per_feed, bool) or not isinstance(max_per_feed, int):
                    raise ValueError("max_per_feed must be an integer")
                if not isinstance(feed_title, str):
                    raise ValueError("feed_title must be a string")
                value = fetch_recent_entries(days, feed_title, max_per_feed)
            else:
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"error": f"Unknown tool: {name}"}, True)}
            return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
        except (ValueError, OSError) as exc:
            return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result({"error": str(exc)}, True)}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def run_stdio() -> None:
    """Serve MCP over newline-delimited JSON-RPC on stdin/stdout."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
            else:
                response = handle_request(message)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio()
