#!/usr/bin/env python3
"""Fetch daily news metadata and public source summaries.

The script stores only metadata, links, and public summaries.
It intentionally does not download or persist full article text.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import dataclasses
import datetime as dt
import hashlib
from html import unescape
import json
import os
import re
import sys
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "sources.yaml"
DEFAULT_STATE = ROOT / "data" / "seen_articles.json"
DEFAULT_DIGEST_DIR = ROOT / "digests"
DEFAULT_DIGEST_INDEX = ROOT / "data" / "digests_index.json"
DEFAULT_HOT_TOPICS = ROOT / "data" / "chinese_hot_topics.json"
DEFAULT_HOT_TOPICS_DIR = ROOT / "data" / "hot_topics"
DEFAULT_HOT_TOPICS_INDEX = ROOT / "data" / "hot_topics_index.json"
DEFAULT_JAPANESE_STATE = ROOT / "data" / "seen_japanese_items.json"
DEFAULT_JAPANESE_DIGEST_DIR = ROOT / "japanese_digests"
DEFAULT_JAPANESE_DIGEST_INDEX = ROOT / "data" / "japanese_digests_index.json"
DEFAULT_TIMEZONE = os.getenv("NEWS_RADAR_TIMEZONE", "Asia/Shanghai")
MAX_FETCH_WORKERS = 8

HOT_TOPIC_SOURCES = [
    {
        "platform": "Baidu",
        "url": "https://top.baidu.com/board?tab=realtime",
    },
    {
        "platform": "Weibo",
        "url": "https://s.weibo.com/top/summary",
    },
]

JAPANESE_SOURCES = [
    {
        "name": "NHK News",
        "outlet": "NHK",
        "url": "https://www3.nhk.or.jp/rss/news/cat0.xml",
        "source_type": "rss",
        "default_topic": "ニュースと社会",
        "article_type_hint": "news",
        "public_access": "likely public",
        "max_items": 16,
    },
    {
        "name": "ITmedia News",
        "outlet": "ITmedia",
        "url": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
        "source_type": "rss",
        "default_topic": "テクノロジーとネット文化",
        "article_type_hint": "tech article",
        "public_access": "likely public",
        "max_items": 16,
    },
    {
        "name": "GIGAZINE",
        "outlet": "GIGAZINE",
        "url": "https://gigazine.net/news/rss_2.0/",
        "source_type": "rss",
        "default_topic": "ネット文化、科学、生活",
        "article_type_hint": "web article",
        "public_access": "likely public",
        "max_items": 16,
    },
    {
        "name": "Impress Watch",
        "outlet": "Impress Watch",
        "url": "https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf",
        "source_type": "rss",
        "default_topic": "IT、製品、暮らし",
        "article_type_hint": "information article",
        "public_access": "likely public",
        "max_items": 16,
    },
]

TARGET_TOPICS = [
    "AI, technology, and daily life",
    "Education, learning, schools, teachers, and students",
    "Youth culture, social media, phones, and mental health",
    "Science discoveries explained for general readers",
    "Health, psychology, habits, sleep, exercise, and wellbeing",
    "Work, careers, creativity, and future skills",
    "Inspiring ordinary people, communities, volunteers, and local change",
    "Culture, language, books, film, music, museums, and art",
    "Environment, animals, climate adaptation, and nature restoration",
    "Cities, housing, transportation, food, and everyday life",
    "Sports stories with strong human or cultural value",
    "Travel, places, traditions, and cross-cultural stories",
    "Justice, inequality, healthcare, and institutions",
    "Award-winning journalism or well-known journalists",
]

BALANCE_HINT = """Prefer a lively daily mix:
- 1-2 short news articles
- 1-2 human-interest or uplifting stories
- 1 science or technology explainer
- 1 education/youth/culture story
- 1 serious public-interest story if available
- 1 wildcard article that is surprising, beautiful, funny, or unusual
Avoid lists that feel too negative, repetitive, partisan, technical, or celebrity-gossip driven."""

JAPANESE_BALANCE_HINT = """Prefer a practical Japanese-learning mix:
- short easy items for N4/N3 learners
- ordinary news or public information with clear structure
- technology, internet culture, lifestyle, food, travel, education, culture, or science explainers
- pages with useful phrases, kanji, particles, sentence endings, honorifics, or written style
- at least one more challenging N1/N2 item when available
Avoid items that are mostly photo galleries, thin celebrity gossip, graphic crime, paywalled pages, or metadata too vague to teach responsibly."""


@dataclasses.dataclass
class Candidate:
    title: str
    outlet: str
    link: str
    source_name: str
    publication_date: str | None
    summary: str
    default_topic: str
    article_type_hint: str
    public_access: str

    @property
    def key(self) -> str:
        normalized = normalize_url(self.link) or self.title.lower().strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


@dataclasses.dataclass
class HotTopicCandidate:
    rank: int
    chinese_topic: str
    platform: str
    heat: str
    source_url: str


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    clean_query_parts = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0].lower()
        if key.startswith("utm_") or key in {"fbclid", "gclid", "cmpid"}:
            continue
        clean_query_parts.append(part)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            "&".join(clean_query_parts),
            "",
        )
    )


def clean_text(value: str | None, limit: int = 480) -> str:
    if not value:
        return ""
    raw = str(value)
    text = (
        BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        if "<" in raw and ">" in raw
        else unescape(raw)
    )
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "..."


def parse_date(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, str):
        try:
            parsed = parsedate_to_datetime(value)
            return parsed.date().isoformat()
        except Exception:
            return value[:10] if re.match(r"\d{4}-\d{2}-\d{2}", value) else None
    return None


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def validate_digest_date(value: str) -> str:
    """Accept canonical ISO dates only, including when used in output paths."""
    try:
        parsed = dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid digest date {value!r}; expected YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"Invalid digest date {value!r}; expected YYYY-MM-DD")
    return value


def validate_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Source configuration must contain a non-empty 'sources' list")

    names: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"Source #{index} must be a mapping")
        name = str(source.get("name", "")).strip()
        url = str(source.get("url", "")).strip()
        source_type = source.get("source_type", "rss")
        if not name or not url:
            raise ValueError(f"Source #{index} must have a name and URL")
        if name in names:
            raise ValueError(f"Duplicate source name: {name}")
        if source_type not in {"rss", "html"}:
            raise ValueError(f"Unsupported source_type {source_type!r} for {name}")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid HTTP(S) URL for {name}: {url}")
        try:
            max_items = int(source.get("max_items", 12))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"max_items for {name} must be an integer") from exc
        if max_items < 1 or max_items > 100:
            raise ValueError(f"max_items for {name} must be between 1 and 100")
        names.add(name)
        validated.append(source)
    return validated


def default_digest_date() -> str:
    return dt.datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date().isoformat()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seen": {}}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = state.setdefault("seen", {})
    if len(seen) > 3000:
        newest = sorted(seen.items(), key=lambda item: item[1].get("first_seen", ""))[-3000:]
        state["seen"] = dict(newest)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def get_with_retry(url: str, timeout: int, user_agent: str) -> requests.Response:
    """Retry transient connection and upstream errors without retrying bad URLs."""
    retryable_statuses = {429, 500, 502, 503, 504}
    last_error: requests.RequestException | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": user_agent},
            )
            if response.status_code in retryable_statuses:
                response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(0.4 * (2**attempt))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def fetch_rss(source: dict[str, Any], timeout: int) -> list[Candidate]:
    response = get_with_retry(source["url"], timeout, "NewsRadarDigest/1.0")
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        detail = f": {parsed.bozo_exception}" if getattr(parsed, "bozo", False) else ""
        raise ValueError(f"RSS feed returned no entries{detail}")
    candidates: list[Candidate] = []
    for entry in parsed.entries[: int(source.get("max_items", 12))]:
        title = clean_text(entry.get("title"), 180)
        link = entry.get("link") or ""
        if not title or not link:
            continue
        summary = clean_text(entry.get("summary") or entry.get("description"), 520)
        published = (
            parse_date(entry.get("published"))
            or parse_date(entry.get("updated"))
            or parse_date(entry.get("created"))
        )
        candidates.append(candidate_from_source(source, title, link, summary, published))
    if not candidates:
        raise ValueError("RSS feed contained no usable article entries")
    return candidates


def fetch_html_index(source: dict[str, Any], timeout: int) -> list[Candidate]:
    """Minimal public-index support for sites without useful RSS.

    Configure with item_selector, title_selector, link_selector, and optional
    summary_selector. This reads index-page metadata only, not article bodies.
    """
    response = get_with_retry(source["url"], timeout, "NewsRadarDigest/1.0")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    items = soup.select(source.get("item_selector", "article"))[: int(source.get("max_items", 12))]
    candidates: list[Candidate] = []
    for item in items:
        title_node = item.select_one(source.get("title_selector", "h2, h3, a"))
        link_node = item.select_one(source.get("link_selector", "a[href]"))
        if not title_node or not link_node:
            continue
        title = clean_text(title_node.get_text(" ", strip=True), 180)
        link = requests.compat.urljoin(source["url"], link_node.get("href"))
        summary_node = item.select_one(source.get("summary_selector", "p"))
        summary = clean_text(summary_node.get_text(" ", strip=True) if summary_node else "", 520)
        candidates.append(candidate_from_source(source, title, link, summary, None))
    if not candidates:
        raise ValueError("HTML index contained no usable article entries; check its selectors")
    return candidates


def candidate_from_source(
    source: dict[str, Any],
    title: str,
    link: str,
    summary: str,
    publication_date: str | None,
) -> Candidate:
    return Candidate(
        title=title,
        outlet=source.get("outlet") or source["name"],
        link=link,
        source_name=source["name"],
        publication_date=publication_date,
        summary=summary,
        default_topic=source.get("default_topic", "General interest"),
        article_type_hint=source.get("article_type_hint", "feature"),
        public_access=source.get("public_access", "unknown"),
    )


def collect_candidates(config: dict[str, Any], timeout: int) -> list[Candidate]:
    """Fetch enabled sources concurrently while preserving configuration order."""
    sources = [source for source in validate_sources(config) if source.get("enabled", True)]
    if not sources:
        raise ValueError("Source configuration has no enabled sources")

    def fetch(source: dict[str, Any]) -> list[Candidate]:
        if source.get("source_type", "rss") == "html":
            return fetch_html_index(source, timeout)
        return fetch_rss(source, timeout)

    results: list[list[Candidate]] = [[] for _ in sources]
    workers = min(MAX_FETCH_WORKERS, len(sources))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {executor.submit(fetch, source): index for index, source in enumerate(sources)}
        for future in as_completed(pending):
            index = pending[future]
            source = sources[index]
            try:
                results[index] = future.result()
                print(f"Fetched {len(results[index]):>2} candidates from {source['name']}")
            except Exception as exc:
                print(f"Warning: failed to fetch {source.get('name')}: {exc}", file=sys.stderr)

    return [candidate for source_results in results for candidate in source_results]


def prefilter(
    candidates: list[Candidate],
    state: dict[str, Any],
    max_candidates: int,
    max_per_outlet: int = 12,
) -> list[Candidate]:
    """Deduplicate and round-robin outlets so high-volume feeds cannot dominate."""
    seen = state.get("seen", {})
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        if candidate.key in seen:
            continue
        unique.setdefault(candidate.key, candidate)
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in unique.values():
        grouped[candidate.outlet].append(candidate)
    for outlet_candidates in grouped.values():
        outlet_candidates.sort(
            key=lambda item: (item.publication_date or "0000-00-00", item.title),
            reverse=True,
        )

    outlets = sorted(
        grouped,
        key=lambda outlet: (
            grouped[outlet][0].publication_date or "0000-00-00",
            outlet.lower(),
        ),
        reverse=True,
    )
    balanced: list[Candidate] = []
    for item_index in range(max_per_outlet):
        for outlet in outlets:
            outlet_candidates = grouped[outlet]
            if item_index < len(outlet_candidates):
                balanced.append(outlet_candidates[item_index])
                if len(balanced) >= max_candidates:
                    return balanced
    return balanced


def decode_json_fragment(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value


def collect_hot_topics(timeout: int, limit: int = 24) -> list[HotTopicCandidate]:
    topics: list[HotTopicCandidate] = []
    seen: set[str] = set()
    for source in HOT_TOPIC_SOURCES:
        try:
            response = get_with_retry(
                source["url"],
                timeout,
                "Mozilla/5.0 NewsRadarDigest/1.0",
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            candidates = []
            selectors = [
                ".c-single-text-ellipsis",
                ".td-02 a",
                "a[href*='weibo.com']",
                "a[href*='baidu.com']",
            ]
            for selector in selectors:
                candidates.extend(clean_text(node.get_text(" ", strip=True), 80) for node in soup.select(selector))
            candidates.extend(decode_json_fragment(match.group(1)) for match in re.finditer(r'"word"\s*:\s*"([^"]+)"', response.text))
            candidates.extend(decode_json_fragment(match.group(1)) for match in re.finditer(r'"note"\s*:\s*"([^"]+)"', response.text))

            for title in candidates:
                title = re.sub(r"^\d+\s*", "", clean_text(title, 80))
                if not title or len(title) < 2 or title in seen:
                    continue
                if any(skip in title for skip in ["更多", "登录", "置顶", "广告"]):
                    continue
                seen.add(title)
                topics.append(
                    HotTopicCandidate(
                        rank=len(topics) + 1,
                        chinese_topic=title,
                        platform=source["platform"],
                        heat="hot",
                        source_url=source["url"],
                )
            )
                if len(topics) >= limit:
                    return topics
        except Exception as exc:
            print(f"Warning: failed to fetch hot topics from {source['platform']}: {exc}", file=sys.stderr)
    return topics


def write_hot_topics(path: Path, digest_date: str, topics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": digest_date,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_note": "Items are collected directly from public trend pages without model processing.",
        "topics": topics,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def update_hot_topics_index(hot_topics_dir: Path, index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for topic_path in sorted(hot_topics_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(topic_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        topics = data.get("topics", [])
        entries.append(
            {
                "date": data.get("date") or topic_path.stem,
                "file": f"data/hot_topics/{topic_path.name}",
                "title": f"Domestic Hot Topics - {data.get('date') or topic_path.stem}",
                "item_count": len(topics) if isinstance(topics, list) else 0,
                "updated_at": data.get("updated_at")
                or dt.datetime.fromtimestamp(topic_path.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds"),
            }
        )
    with index_path.open("w", encoding="utf-8") as handle:
        json.dump({"digests": entries}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_hot_topics_outputs(
    latest_path: Path,
    hot_topics_dir: Path,
    index_path: Path,
    digest_date: str,
    topics: list[dict[str, Any]],
) -> Path:
    dated_path = hot_topics_dir / f"{digest_date}.json"
    write_hot_topics(dated_path, digest_date, topics)
    write_hot_topics(latest_path, digest_date, topics)
    update_hot_topics_index(hot_topics_dir, index_path)
    return dated_path


def generate_hot_topics(
    path: Path,
    hot_topics_dir: Path,
    index_path: Path,
    digest_date: str,
    timeout: int,
    count: int = 8,
) -> list[dict[str, Any]]:
    candidates = collect_hot_topics(timeout)
    if not candidates:
        raise RuntimeError("No Chinese hot-topic candidates found")
    topics = [dataclasses.asdict(candidate) for candidate in candidates[:count]]
    write_hot_topics_outputs(path, hot_topics_dir, index_path, digest_date, topics)
    return topics


def md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").strip()


def raw_items(candidates: list[Candidate], count: int) -> list[dict[str, Any]]:
    return [{"id": candidate.key, **dataclasses.asdict(candidate)} for candidate in candidates[:count]]


def render_digest(path: Path, digest_date: str, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_sections = []
    if path.exists():
        existing_sections = re.split(r"^##\s+", path.read_text(encoding="utf-8"), flags=re.MULTILINE)[1:]
    new_links = {str(item.get("link", "")) for item in items}
    lines = [f"# News Radar - {digest_date}", "", "Public source metadata and summaries.", ""]
    for index, item in enumerate(items, 1):
        lines.extend([
            f"## {index}. {md_escape(item.get('title'))}", "",
            f"- **Outlet:** {md_escape(item.get('outlet'))}",
            f"- **Publication date:** {md_escape(item.get('publication_date') or 'Not listed')}",
            f"- **Link:** {md_escape(item.get('link'))}",
            f"- **Summary:** {md_escape(item.get('summary') or '')}", "",
        ])
    # Preserve earlier same-day items while replacing refreshed entries by URL.
    for section in existing_sections:
        match = re.search(r"^- \*\*Link:\*\*\s*(.*)$", section, re.MULTILINE)
        if match and match.group(1).strip() not in new_links:
            heading, _, body = section.partition("\n")
            heading = re.sub(r"^\d+\.\s*", "", heading)
            index = sum(line.startswith("## ") for line in lines) + 1
            lines.append(f"## {index}. {heading}\n{body.rstrip()}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def render_japanese_digest(path: Path, digest_date: str, items: list[dict[str, Any]]) -> None:
    render_digest(path, digest_date, items)


def update_seen(state: dict[str, Any], items: list[dict[str, Any]], digest_date: str) -> None:
    seen = state.setdefault("seen", {})
    for item in items:
        key = str(item.get("id") or hashlib.sha256(str(item.get("link", "")).encode("utf-8")).hexdigest()[:20])
        seen.setdefault(
            key,
            {
                "title": item.get("title"),
                "link": normalize_url(str(item.get("link", ""))),
                "first_seen": digest_date,
            },
        )


def update_digest_index(digest_dir: Path, index_path: Path, file_prefix: str = "digests") -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for digest_path in sorted(digest_dir.glob("*.md"), reverse=True):
        text = digest_path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        item_count = len(re.findall(r"^##\s+\d+\.", text, flags=re.MULTILINE))
        entries.append(
            {
                "date": digest_path.stem,
                "file": f"{file_prefix}/{digest_path.name}",
                "title": title_match.group(1).strip() if title_match else digest_path.stem,
                "item_count": item_count,
                "updated_at": dt.datetime.fromtimestamp(
                    digest_path.stat().st_mtime,
                    dt.timezone.utc,
                ).isoformat(timespec="seconds"),
            }
        )
    with index_path.open("w", encoding="utf-8") as handle:
        json.dump({"digests": entries}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def generate_japanese_digest(
    digest_date: str,
    state_path: Path,
    output_dir: Path,
    index_path: Path,
    count: int,
    max_candidates: int,
    timeout: int,
) -> list[dict[str, Any]]:
    state = load_state(state_path)
    candidates = collect_candidates({"sources": JAPANESE_SOURCES}, timeout)
    candidates = prefilter(candidates, state, max_candidates)
    if not candidates:
        if (output_dir / f"{digest_date}.md").exists():
            return []
        raise RuntimeError("No new Japanese candidate items found after fetching and deduplication")

    items = raw_items(candidates, count)

    if not items:
        raise RuntimeError("No Japanese items were selected")

    digest_path = output_dir / f"{digest_date}.md"
    render_japanese_digest(digest_path, digest_date, items)
    update_seen(state, items, digest_date)
    save_state(state_path, state)
    update_digest_index(output_dir, index_path, "japanese_digests")
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=default_digest_date())
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIGEST_DIR)
    parser.add_argument("--index", type=Path, default=DEFAULT_DIGEST_INDEX)
    parser.add_argument("--hot-topics-output", type=Path, default=DEFAULT_HOT_TOPICS)
    parser.add_argument("--hot-topics-dir", type=Path, default=DEFAULT_HOT_TOPICS_DIR)
    parser.add_argument("--hot-topics-index", type=Path, default=DEFAULT_HOT_TOPICS_INDEX)
    parser.add_argument("--japanese-state", type=Path, default=DEFAULT_JAPANESE_STATE)
    parser.add_argument("--japanese-output-dir", type=Path, default=DEFAULT_JAPANESE_DIGEST_DIR)
    parser.add_argument("--japanese-index", type=Path, default=DEFAULT_JAPANESE_DIGEST_INDEX)
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--japanese-count", type=int, default=80)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--no-llm", action="store_true", help="Deprecated compatibility flag; all runs fetch metadata only.")
    parser.add_argument("--topics-only", action="store_true", help="Update Chinese hot topics without generating a digest.")
    parser.add_argument("--skip-hot-topics", action="store_true", help="Generate the digest without updating Chinese hot topics.")
    parser.add_argument("--japanese-only", action="store_true", help="Update Japanese items without generating the English digest.")
    parser.add_argument("--skip-japanese", action="store_true", help="Generate the English digest without updating Japanese items.")
    args = parser.parse_args()

    try:
        args.date = validate_digest_date(args.date)
    except ValueError as exc:
        parser.error(str(exc))
    if args.count < 1 or args.japanese_count < 1:
        parser.error("--count and --japanese-count must be positive")
    if args.max_candidates < max(args.count, args.japanese_count):
        parser.error("--max-candidates must be at least as large as the requested item counts")
    if args.timeout < 1:
        parser.error("--timeout must be positive")

    if args.topics_only:
        topics = generate_hot_topics(
            args.hot_topics_output,
            args.hot_topics_dir,
            args.hot_topics_index,
            args.date,
            args.timeout,
        )
        print(f"Wrote {args.hot_topics_dir / (args.date + '.json')} with {len(topics)} hot topics")
        return 0

    if args.japanese_only:
        items = generate_japanese_digest(
            args.date,
            args.japanese_state,
            args.japanese_output_dir,
            args.japanese_index,
            args.japanese_count,
            args.max_candidates,
            args.timeout,
        )
        print(f"Wrote {args.japanese_output_dir / (args.date + '.md')} with {len(items)} Japanese items")
        return 0

    config = load_yaml(args.sources)
    state = load_state(args.state)
    candidates = collect_candidates(config, args.timeout)
    candidates = prefilter(candidates, state, args.max_candidates)
    if not candidates:
        if (args.output_dir / f"{args.date}.md").exists():
            print("No new English items; retaining today's collected items")
        else:
            raise RuntimeError("No new candidate articles found after fetching and deduplication")

    items = raw_items(candidates, args.count)

    digest_path = args.output_dir / f"{args.date}.md"
    render_digest(digest_path, args.date, items)
    update_seen(state, items, args.date)
    save_state(args.state, state)
    update_digest_index(args.output_dir, args.index)
    if not args.skip_hot_topics:
        try:
            topics = generate_hot_topics(
                args.hot_topics_output,
                args.hot_topics_dir,
                args.hot_topics_index,
                args.date,
                args.timeout,
            )
            print(f"Wrote {args.hot_topics_dir / (args.date + '.json')} with {len(topics)} hot topics")
        except Exception as exc:
            print(f"Warning: failed to update Chinese hot topics: {exc}", file=sys.stderr)
    if not args.skip_japanese:
        try:
            japanese_items = generate_japanese_digest(
                args.date,
                args.japanese_state,
                args.japanese_output_dir,
                args.japanese_index,
                args.japanese_count,
                args.max_candidates,
                args.timeout,
            )
            print(f"Wrote {args.japanese_output_dir / (args.date + '.md')} with {len(japanese_items)} Japanese items")
        except Exception as exc:
            print(f"Warning: failed to update Japanese items: {exc}", file=sys.stderr)
    print(f"Wrote {digest_path} with {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
