#!/usr/bin/env python3
"""Fetch RSS feeds, extract article text, and write a daily aggregated archive."""

import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RETENTION_DAYS = 30
MIN_CONTENT_LENGTH = 100
USER_AGENT = "rss-archive/1.0 (+https://github.com/17678319606/rss-archive)"


def clean_content(html_or_text):
    """Remove markup and common navigation/ad/tracking noise from article text."""
    soup = BeautifulSoup(html_or_text or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "form", "nav", "header", "footer", "aside"]):
        tag.decompose()
    for tag in soup.find_all(True):
        marker = " ".join(tag.get("class", [])) + " " + tag.get("id", "")
        if re.search(r"ad[sx]?|advert|sponsor|promo|banner|cookie|consent|newsletter|subscribe|social|share|tracking|related", marker, re.I):
            tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:advertisement|sponsored content|subscribe now|sign up for our newsletter).*?(?=\.|$)", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def element_text(item, *names):
    for name in names:
        child = item.find(name)
        if child is not None:
            value = child.get_text(" ", strip=True)
            if value:
                return value
    return ""


def parse_feed(payload):
    soup = BeautifulSoup(payload, "xml")
    entries = soup.find_all("item") or soup.find_all("entry")
    result = []
    for item in entries:
        link_tag = item.find("link")
        link = (link_tag.get("href", "") if link_tag else "") or element_text(item, "link")
        result.append({
            "title": element_text(item, "title"),
            "link": link.strip(),
            "guid": element_text(item, "guid", "id"),
            "published": element_text(item, "pubDate", "published", "updated"),
            "description": element_text(item, "description", "summary", "content", "encoded"),
        })
    return result


def extract_article(url, fallback):
    if not url:
        return ""
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "form", "nav", "header", "footer", "aside"]):
            tag.decompose()
        candidates = soup.find_all(["article", "main"]) or soup.find_all("div")
        best = max((clean_content(node) for node in candidates), key=len, default="")
        return best if len(best) >= MIN_CONTENT_LENGTH else clean_content(fallback)
    except requests.RequestException as exc:
        print(f"Article fetch failed for {url}: {exc}")
        return clean_content(fallback)


def stable_id(item):
    value = item["guid"] or item["link"] or item["title"]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def main():
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    today = dt.date.today()
    day_dir = DATA_DIR / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    daily_path = day_dir / "daily_data.json"
    existing = json.loads(daily_path.read_text(encoding="utf-8")) if daily_path.exists() else []
    by_id = {item["id"]: item for item in existing if isinstance(item, dict) and item.get("id")}

    for feed_url in sources:
        try:
            response = requests.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=30)
            response.raise_for_status()
            for item in parse_feed(response.content):
                content = extract_article(item["link"], item["description"])
                if len(content) < MIN_CONTENT_LENGTH:
                    print(f"Skipped short item: {item['title']}")
                    continue
                by_id[stable_id(item)] = {
                    "id": stable_id(item),
                    "source": urlparse(feed_url).netloc or feed_url,
                    "title": item["title"],
                    "content_full": content,
                    "url": item["link"],
                    "timestamp": item["published"] or dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            print(f"Fetched {feed_url}: {len(parse_feed(response.content))} items")
        except requests.RequestException as exc:
            print(f"Feed fetch failed for {feed_url}: {exc}")

    daily_path.write_text(json.dumps(sorted(by_id.values(), key=lambda x: x["timestamp"], reverse=True), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for old_dir in DATA_DIR.iterdir() if DATA_DIR.exists() else []:
        if old_dir.is_dir():
            try:
                if (today - dt.date.fromisoformat(old_dir.name)).days > RETENTION_DAYS:
                    shutil.rmtree(old_dir)
            except ValueError:
                pass
    print(f"Wrote {len(by_id)} articles to {daily_path}")


if __name__ == "__main__":
    main()
