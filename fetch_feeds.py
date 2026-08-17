#!/usr/bin/env python3
"""Fetch configured RSS feeds into a date-partitioned archive."""

import datetime as dt
import json
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RETENTION_DAYS = 30


def text(element, name):
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def parse_feed(payload):
    root = ET.fromstring(payload)
    channel = root.find("channel")
    entries = channel.findall("item") if channel is not None else root.findall("{*}entry")
    result = []
    for item in entries:
        result.append({
            "title": text(item, "title") or text(item, "{*}title"),
            "link": text(item, "link") or next((x.attrib.get("href", "") for x in item.findall("{*}link") if x.attrib.get("href")), ""),
            "guid": text(item, "guid") or text(item, "{*}id"),
            "published": text(item, "pubDate") or text(item, "{*}published") or text(item, "{*}updated"),
            "description": text(item, "description") or text(item, "{*}summary") or text(item, "{*}content"),
        })
    return result


def main():
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    today = dt.date.today()
    day_dir = DATA_DIR / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    for old_dir in DATA_DIR.iterdir() if DATA_DIR.exists() else []:
        if old_dir.is_dir():
            try:
                age = (today - dt.date.fromisoformat(old_dir.name)).days
            except ValueError:
                continue
            if age > RETENTION_DAYS:
                shutil.rmtree(old_dir)
    for url in sources:
        topic_id = url.rstrip("/").split("/")[-1]
        output = {"source": url, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "items": [], "error": None}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "rss-archive/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                output["items"] = parse_feed(response.read())
        except Exception as exc:
            output["error"] = f"{type(exc).__name__}: {exc}"
            print(f"Failed {topic_id}: {output['error']}")
        (day_dir / f"{topic_id}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Fetched {topic_id}: {len(output['items'])} items")


if __name__ == "__main__":
    main()
