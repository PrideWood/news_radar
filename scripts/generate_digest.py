#!/usr/bin/env python3
"""Generate a daily English close-reading news recommendation digest.

The script stores only metadata, links, public summaries, and teaching notes.
It intentionally does not download or persist full article text.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import sys
import textwrap
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

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - requirements installs this in CI.
    OpenAI = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "sources.yaml"
DEFAULT_STATE = ROOT / "data" / "seen_articles.json"
DEFAULT_DIGEST_DIR = ROOT / "digests"
DEFAULT_DIGEST_INDEX = ROOT / "data" / "digests_index.json"
DEFAULT_HOT_TOPICS = ROOT / "data" / "chinese_hot_topics.json"
DEFAULT_JAPANESE_STATE = ROOT / "data" / "seen_japanese_items.json"
DEFAULT_JAPANESE_DIGEST_DIR = ROOT / "japanese_digests"
DEFAULT_JAPANESE_DIGEST_INDEX = ROOT / "data" / "japanese_digests_index.json"
DEFAULT_TIMEZONE = os.getenv("NEWS_RADAR_TIMEZONE", "Asia/Shanghai")

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

OFFICIAL_ENGLISH_SOURCES = [
    {
        "outlet": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/china_rss.xml",
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
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
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


def fetch_rss(source: dict[str, Any], timeout: int) -> list[Candidate]:
    response = requests.get(
        source["url"],
        timeout=timeout,
        headers={"User-Agent": "NewsRadarDigest/1.0"},
    )
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
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
    return candidates


def fetch_html_index(source: dict[str, Any], timeout: int) -> list[Candidate]:
    """Minimal public-index support for sites without useful RSS.

    Configure with item_selector, title_selector, link_selector, and optional
    summary_selector. This reads index-page metadata only, not article bodies.
    """
    response = requests.get(
        source["url"],
        timeout=timeout,
        headers={"User-Agent": "NewsRadarDigest/1.0"},
    )
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
    candidates: list[Candidate] = []
    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        try:
            source_type = source.get("source_type", "rss")
            if source_type == "html":
                found = fetch_html_index(source, timeout)
            else:
                found = fetch_rss(source, timeout)
            candidates.extend(found)
            time.sleep(0.25)
        except Exception as exc:
            print(f"Warning: failed to fetch {source.get('name')}: {exc}", file=sys.stderr)
    return candidates


def is_probably_relevant(candidate: Candidate) -> bool:
    text = f"{candidate.title} {candidate.summary} {candidate.default_topic}".lower()
    avoid = [
        "stock market",
        "shares fall",
        "earnings call",
        "celebrity gossip",
        "graphic video",
        "murder trial",
    ]
    if any(term in text for term in avoid):
        return False
    return True


def prefilter(candidates: list[Candidate], state: dict[str, Any], max_candidates: int) -> list[Candidate]:
    seen = state.get("seen", {})
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        if candidate.key in seen:
            continue
        if not is_probably_relevant(candidate):
            continue
        unique.setdefault(candidate.key, candidate)
    dated = sorted(
        unique.values(),
        key=lambda item: (item.publication_date or "0000-00-00", item.outlet, item.title),
        reverse=True,
    )
    return dated[:max_candidates]


def build_llm_prompt(candidates: list[Candidate], count: int) -> str:
    payload = [
        {
            "id": candidate.key,
            "title": candidate.title,
            "outlet": candidate.outlet,
            "publication_date": candidate.publication_date,
            "link": candidate.link,
            "source_topic_hint": candidate.default_topic,
            "article_type_hint": candidate.article_type_hint,
            "public_access_hint": candidate.public_access,
            "public_summary_or_excerpt": candidate.summary,
        }
        for candidate in candidates
    ]
    return textwrap.dedent(
        f"""
        You are selecting English news/article recommendations for short close-reading videos.
        Choose {count} articles from the candidate metadata below.

        Selection goals:
        {BALANCE_HINT}

        Topic menu:
        {json.dumps(TARGET_TOPICS, ensure_ascii=False)}

        For each selected item, return:
        id, title, outlet, publication_date, link, topic, article_type, tone,
        why_it_is_worth_teaching, why_ordinary_viewers_may_care, language_value,
        suggested_video_angle, expressions_to_teach (3-5 strings),
        estimated_difficulty (B1/B2/C1/C2), estimated_video_length (5 min/10 min/15 min),
        publicly_accessible, priority_score (1-10).

        Use only the supplied metadata and public summary/excerpt. Do not invent article facts.
        Favor clear English, human interest, practical insight, science/culture explainers,
        and stories with warmth, curiosity, or public-interest value.

        Return strict JSON with this shape:
        {{"recommendations":[{{...}}]}}

        Candidates:
        {json.dumps(payload, ensure_ascii=False, indent=2)}
        """
    ).strip()


def call_llm(candidates: list[Candidate], count: int) -> list[dict[str, Any]]:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    base_url = os.getenv("OPENAI_BASE_URL")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        temperature=0.35,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You are a careful editor for English close-reading video lessons.",
            },
            {"role": "user", "content": build_llm_prompt(candidates, count)},
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    recommendations = parsed.get("recommendations", [])
    if not isinstance(recommendations, list):
        raise RuntimeError("LLM response did not contain a recommendations list")
    return recommendations


def build_japanese_llm_prompt(candidates: list[Candidate], count: int) -> str:
    payload = [
        {
            "id": candidate.key,
            "title": candidate.title,
            "outlet": candidate.outlet,
            "publication_date": candidate.publication_date,
            "link": candidate.link,
            "source_topic_hint": candidate.default_topic,
            "material_type_hint": candidate.article_type_hint,
            "public_access_hint": candidate.public_access,
            "public_summary_or_excerpt": candidate.summary,
        }
        for candidate in candidates
    ]
    return textwrap.dedent(
        f"""
        You are selecting Japanese close-reading recommendations for Chinese-speaking Japanese learners.
        Choose {count} public Japanese-language items from the candidate metadata below.

        Selection goals:
        {JAPANESE_BALANCE_HINT}

        For each selected item, return:
        id, title, outlet, publication_date, link, topic, article_type, tone,
        why_it_is_worth_teaching, why_ordinary_viewers_may_care, language_value,
        suggested_video_angle, expressions_to_teach (3-5 Japanese strings),
        estimated_difficulty (N4/N3/N2/N1), estimated_video_length (5 min/10 min/15 min),
        publicly_accessible, priority_score (1-10).

        Use only the supplied metadata and public summary/excerpt. Do not invent article facts.
        The item does not have to be hard news; public internet pages with strong language-learning value are welcome.
        Favor useful vocabulary, natural collocations, particles, sentence endings, kanji words, polite/plain style contrasts,
        and clear written Japanese.

        Return strict JSON with this shape:
        {{"recommendations":[{{...}}]}}

        Candidates:
        {json.dumps(payload, ensure_ascii=False, indent=2)}
        """
    ).strip()


def call_japanese_llm(candidates: list[Candidate], count: int) -> list[dict[str, Any]]:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    base_url = os.getenv("OPENAI_BASE_URL")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        temperature=0.35,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You are a careful editor for Japanese close-reading lessons. Be practical, concise, and learner-focused.",
            },
            {"role": "user", "content": build_japanese_llm_prompt(candidates, count)},
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    recommendations = parsed.get("recommendations", [])
    if not isinstance(recommendations, list):
        raise RuntimeError("LLM response did not contain a recommendations list")
    return recommendations


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
            response = requests.get(
                source["url"],
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 NewsRadarDigest/1.0"},
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


def collect_official_english_headlines(timeout: int, limit: int = 36) -> list[dict[str, str]]:
    headlines: list[dict[str, str]] = []
    for source in OFFICIAL_ENGLISH_SOURCES:
        try:
            response = requests.get(
                source["url"],
                timeout=timeout,
                headers={"User-Agent": "NewsRadarDigest/1.0"},
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            for entry in parsed.entries[:limit]:
                title = clean_text(entry.get("title"), 180)
                link = entry.get("link") or source["url"]
                if title:
                    headlines.append({"outlet": source["outlet"], "title": title, "url": link})
        except Exception as exc:
            print(f"Warning: failed to fetch official English headlines from {source['outlet']}: {exc}", file=sys.stderr)
    return headlines[:limit]


def build_hot_topics_prompt(
    candidates: list[HotTopicCandidate],
    official_headlines: list[dict[str, str]],
    count: int,
    digest_date: str,
) -> str:
    payload = [dataclasses.asdict(topic) for topic in candidates]
    return textwrap.dedent(
        f"""
        You are preparing shareable topic leads for a Chinese creator who explains news in English.
        Select the {count} strongest topics from today's Chinese internet hot-topic candidates.

        Date: {digest_date}

        Goals:
        - Prefer public-interest, technology, education, culture, economy, science, travel, sports, or livelihood topics.
        - Avoid pure celebrity gossip, fan-club disputes, graphic crime, and topics that cannot be responsibly summarized from a headline.
        - If an official English headline below clearly matches a Chinese topic, use that headline and source URL.
        - If no official match is clear, write a neutral official-style English wording and set official_english_source to "Suggested wording".
        - Do not invent concrete facts beyond the supplied Chinese topic text and official English headlines.

        Return strict JSON:
        {{
          "topics": [
            {{
              "rank": 1,
              "chinese_topic": "...",
              "platform": "...",
              "heat": "...",
              "official_english": "...",
              "official_english_source": "...",
              "official_english_url": "...",
              "why_hot": "...",
              "share_angle": "...",
              "keywords": ["...", "...", "..."]
            }}
          ]
        }}

        Chinese hot-topic candidates:
        {json.dumps(payload, ensure_ascii=False, indent=2)}

        Official English headline candidates:
        {json.dumps(official_headlines, ensure_ascii=False, indent=2)}
        """
    ).strip()


def call_hot_topics_llm(
    candidates: list[HotTopicCandidate],
    official_headlines: list[dict[str, str]],
    count: int,
    digest_date: str,
) -> list[dict[str, Any]]:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    base_url = os.getenv("OPENAI_BASE_URL")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        temperature=0.25,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You are a careful bilingual news editor. Be concise, neutral, and transparent about uncertainty.",
            },
            {"role": "user", "content": build_hot_topics_prompt(candidates, official_headlines, count, digest_date)},
        ],
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    topics = parsed.get("topics", [])
    if not isinstance(topics, list):
        raise RuntimeError("LLM response did not contain a topics list")
    return topics


def heuristic_hot_topics(candidates: list[HotTopicCandidate], count: int) -> list[dict[str, Any]]:
    picked = []
    for candidate in candidates[:count]:
        picked.append(
            {
                "rank": candidate.rank,
                "chinese_topic": candidate.chinese_topic,
                "platform": candidate.platform,
                "heat": candidate.heat,
                "official_english": f"Chinese online users discuss: {candidate.chinese_topic}",
                "official_english_source": "Suggested wording",
                "official_english_url": "",
                "why_hot": "This topic appeared in a public Chinese hot-topic list and may be useful as a timely discussion lead.",
                "share_angle": "Use the Chinese topic as the hook, then ask what neutral English wording best captures it.",
                "keywords": ["Chinese web", "hot topic", "English framing"],
            }
        )
    return picked


def write_hot_topics(path: Path, digest_date: str, topics: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": digest_date,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_note": "Chinese hot-topic candidates are collected from public trend pages; English wording is matched to supplied official English headlines when possible, otherwise suggested neutrally.",
        "topics": topics,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def generate_hot_topics(path: Path, digest_date: str, timeout: int, no_llm: bool, count: int = 3) -> list[dict[str, Any]]:
    candidates = collect_hot_topics(timeout)
    if not candidates:
        raise RuntimeError("No Chinese hot-topic candidates found")
    official_headlines = collect_official_english_headlines(timeout)
    if no_llm:
        topics = heuristic_hot_topics(candidates, count)
    else:
        try:
            topics = call_hot_topics_llm(candidates, official_headlines, count, digest_date)
        except Exception as exc:
            print(f"Warning: failed to generate hot topics with LLM, using fallback: {exc}", file=sys.stderr)
            topics = heuristic_hot_topics(candidates, count)
    topics = topics[:count]
    write_hot_topics(path, digest_date, topics)
    return topics


def heuristic_recommendations(candidates: list[Candidate], count: int) -> list[dict[str, Any]]:
    """Development fallback used when no API key is available."""
    topic_keywords = [
        ("AI, technology, and daily life", ["ai", "technology", "app", "robot", "phone"]),
        ("Education, learning, schools, teachers, and students", ["school", "student", "teacher", "college"]),
        ("Science discoveries explained for general readers", ["science", "study", "research", "space", "climate"]),
        ("Health, psychology, habits, sleep, exercise, and wellbeing", ["health", "sleep", "exercise", "mental"]),
        ("Culture, language, books, film, music, museums, and art", ["book", "film", "music", "museum", "art"]),
        ("Environment, animals, climate adaptation, and nature restoration", ["climate", "wildlife", "nature", "river"]),
    ]
    picked: list[dict[str, Any]] = []
    used_outlets: set[str] = set()
    for candidate in candidates:
        text = f"{candidate.title} {candidate.summary}".lower()
        topic = candidate.default_topic
        for possible, keywords in topic_keywords:
            if any(keyword in text for keyword in keywords):
                topic = possible
                break
        score = 8 if candidate.outlet not in used_outlets else 6
        used_outlets.add(candidate.outlet)
        picked.append(
            {
                "id": candidate.key,
                "title": candidate.title,
                "outlet": candidate.outlet,
                "publication_date": candidate.publication_date,
                "link": candidate.link,
                "topic": topic,
                "article_type": candidate.article_type_hint,
                "tone": "curious",
                "why_it_is_worth_teaching": "The metadata suggests a clear, current story with useful vocabulary and room for close reading.",
                "why_ordinary_viewers_may_care": "It connects a public issue or everyday trend to questions viewers can discuss from daily life.",
                "language_value": "Good for practicing headline language, concise summaries, cause-and-effect phrasing, and evaluative adjectives.",
                "suggested_video_angle": "Open with the question behind the headline, then unpack the article's key claim and useful expressions.",
                "expressions_to_teach": ["shed light on", "raise questions about", "a growing trend", "in everyday life"],
                "estimated_difficulty": "B2",
                "estimated_video_length": "10 min",
                "publicly_accessible": candidate.public_access,
                "priority_score": score,
            }
        )
        if len(picked) >= count:
            break
    return picked


def heuristic_japanese_recommendations(candidates: list[Candidate], count: int) -> list[dict[str, Any]]:
    """Development fallback used when no API key is available."""
    levels = ["N4", "N3", "N2", "N1"]
    picked: list[dict[str, Any]] = []
    used_outlets: set[str] = set()
    for index, candidate in enumerate(candidates):
        level = levels[min(index % len(levels), len(levels) - 1)]
        score = 8 if candidate.outlet not in used_outlets else 6
        used_outlets.add(candidate.outlet)
        picked.append(
            {
                "id": candidate.key,
                "title": candidate.title,
                "outlet": candidate.outlet,
                "publication_date": candidate.publication_date,
                "link": candidate.link,
                "topic": candidate.default_topic,
                "article_type": candidate.article_type_hint,
                "tone": "実用的",
                "why_it_is_worth_teaching": "公開メタデータから、語彙・文型・書き言葉の観察に使いやすい題材だと判断できます。",
                "why_ordinary_viewers_may_care": "日本語学習者がニュース、ネット文化、日常生活の語彙を自然な文脈で確認できます。",
                "language_value": "見出し表現、漢字語、助詞、連体修飾、文末表現を短い精読で扱いやすい素材です。",
                "suggested_video_angle": "見出しのキーワードを確認し、本文で使われる自然な言い換えや文型を拾って解説する。",
                "expressions_to_teach": ["〜について", "〜によると", "〜として", "〜をめぐる"],
                "estimated_difficulty": level,
                "estimated_video_length": "10 min",
                "publicly_accessible": candidate.public_access,
                "priority_score": score,
            }
        )
        if len(picked) >= count:
            break
    return picked


def ensure_candidate_fields(recommendation: dict[str, Any], candidate_by_id: dict[str, Candidate]) -> dict[str, Any]:
    candidate = candidate_by_id.get(str(recommendation.get("id", "")))
    if candidate:
        recommendation.setdefault("title", candidate.title)
        recommendation.setdefault("outlet", candidate.outlet)
        recommendation.setdefault("publication_date", candidate.publication_date)
        recommendation.setdefault("link", candidate.link)
        recommendation.setdefault("publicly_accessible", candidate.public_access)
    return recommendation


def md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").strip()


def render_digest(path: Path, digest_date: str, recommendations: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Daily English Close-Reading Recommendations - {digest_date}",
        "",
        "A balanced set of public English articles for short close-reading videos. The notes are based on source metadata, links, and short public summaries/previews only.",
        "",
    ]
    for index, item in enumerate(recommendations, start=1):
        expressions = item.get("expressions_to_teach") or item.get("suggested_expressions") or []
        if isinstance(expressions, str):
            expressions = [expressions]
        lines.extend(
            [
                f"## {index}. {md_escape(item.get('title'))}",
                "",
                f"- **Outlet:** {md_escape(item.get('outlet'))}",
                f"- **Publication date:** {md_escape(item.get('publication_date') or 'Not listed')}",
                f"- **Link:** {md_escape(item.get('link'))}",
                f"- **Topic:** {md_escape(item.get('topic'))}",
                f"- **Article type:** {md_escape(item.get('article_type'))}",
                f"- **Tone:** {md_escape(item.get('tone'))}",
                f"- **Why it is worth teaching:** {md_escape(item.get('why_it_is_worth_teaching'))}",
                f"- **Why ordinary viewers may care:** {md_escape(item.get('why_ordinary_viewers_may_care'))}",
                f"- **Language value:** {md_escape(item.get('language_value'))}",
                f"- **Suggested video angle:** {md_escape(item.get('suggested_video_angle'))}",
                f"- **Suggested expressions to teach:** {', '.join(md_escape(expr) for expr in expressions[:5])}",
                f"- **Estimated difficulty:** {md_escape(item.get('estimated_difficulty'))}",
                f"- **Estimated video length:** {md_escape(item.get('estimated_video_length'))}",
                f"- **Seems publicly accessible:** {md_escape(item.get('publicly_accessible'))}",
                f"- **Priority score:** {md_escape(item.get('priority_score'))}/10",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def render_japanese_digest(path: Path, digest_date: str, recommendations: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Daily Japanese Close-Reading Recommendations - {digest_date}",
        "",
        "A balanced set of public Japanese-language materials for short close-reading lessons. The notes are based on source metadata, links, and short public summaries/previews only.",
        "",
    ]
    for index, item in enumerate(recommendations, start=1):
        expressions = item.get("expressions_to_teach") or item.get("suggested_expressions") or []
        if isinstance(expressions, str):
            expressions = [expressions]
        lines.extend(
            [
                f"## {index}. {md_escape(item.get('title'))}",
                "",
                f"- **Outlet:** {md_escape(item.get('outlet'))}",
                f"- **Publication date:** {md_escape(item.get('publication_date') or 'Not listed')}",
                f"- **Link:** {md_escape(item.get('link'))}",
                f"- **Topic:** {md_escape(item.get('topic'))}",
                f"- **Article type:** {md_escape(item.get('article_type'))}",
                f"- **Tone:** {md_escape(item.get('tone'))}",
                f"- **Why it is worth teaching:** {md_escape(item.get('why_it_is_worth_teaching'))}",
                f"- **Why ordinary viewers may care:** {md_escape(item.get('why_ordinary_viewers_may_care'))}",
                f"- **Language value:** {md_escape(item.get('language_value'))}",
                f"- **Suggested video angle:** {md_escape(item.get('suggested_video_angle'))}",
                f"- **Suggested expressions to teach:** {', '.join(md_escape(expr) for expr in expressions[:5])}",
                f"- **Estimated difficulty:** {md_escape(item.get('estimated_difficulty'))}",
                f"- **Estimated video length:** {md_escape(item.get('estimated_video_length'))}",
                f"- **Seems publicly accessible:** {md_escape(item.get('publicly_accessible'))}",
                f"- **Priority score:** {md_escape(item.get('priority_score'))}/10",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def update_seen(state: dict[str, Any], recommendations: list[dict[str, Any]], digest_date: str) -> None:
    seen = state.setdefault("seen", {})
    for item in recommendations:
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
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
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
    no_llm: bool,
) -> list[dict[str, Any]]:
    state = load_state(state_path)
    candidates = collect_candidates({"sources": JAPANESE_SOURCES}, timeout)
    candidates = prefilter(candidates, state, max_candidates)
    if not candidates:
        raise RuntimeError("No new Japanese candidate items found after fetching and deduplication")

    candidate_by_id = {candidate.key: candidate for candidate in candidates}
    if no_llm:
        recommendations = heuristic_japanese_recommendations(candidates, count)
    else:
        recommendations = call_japanese_llm(candidates, count)
    recommendations = [
        ensure_candidate_fields(item, candidate_by_id)
        for item in recommendations
        if item.get("id") in candidate_by_id or item.get("link")
    ][:count]

    if not recommendations:
        raise RuntimeError("No Japanese recommendations were selected")

    digest_path = output_dir / f"{digest_date}.md"
    render_japanese_digest(digest_path, digest_date, recommendations)
    update_seen(state, recommendations, digest_date)
    save_state(state_path, state)
    update_digest_index(output_dir, index_path, "japanese_digests")
    return recommendations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=default_digest_date())
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIGEST_DIR)
    parser.add_argument("--index", type=Path, default=DEFAULT_DIGEST_INDEX)
    parser.add_argument("--hot-topics-output", type=Path, default=DEFAULT_HOT_TOPICS)
    parser.add_argument("--japanese-state", type=Path, default=DEFAULT_JAPANESE_STATE)
    parser.add_argument("--japanese-output-dir", type=Path, default=DEFAULT_JAPANESE_DIGEST_DIR)
    parser.add_argument("--japanese-index", type=Path, default=DEFAULT_JAPANESE_DIGEST_INDEX)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--japanese-count", type=int, default=8)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic fallback for local smoke tests.")
    parser.add_argument("--topics-only", action="store_true", help="Update Chinese hot topics without generating a digest.")
    parser.add_argument("--skip-hot-topics", action="store_true", help="Generate the digest without updating Chinese hot topics.")
    parser.add_argument("--japanese-only", action="store_true", help="Update Japanese close-reading recommendations without generating the English digest.")
    parser.add_argument("--skip-japanese", action="store_true", help="Generate the English digest without updating Japanese recommendations.")
    args = parser.parse_args()

    if args.topics_only:
        topics = generate_hot_topics(args.hot_topics_output, args.date, args.timeout, args.no_llm)
        print(f"Wrote {args.hot_topics_output} with {len(topics)} hot topics")
        return 0

    if args.japanese_only:
        recommendations = generate_japanese_digest(
            args.date,
            args.japanese_state,
            args.japanese_output_dir,
            args.japanese_index,
            args.japanese_count,
            args.max_candidates,
            args.timeout,
            args.no_llm,
        )
        print(f"Wrote {args.japanese_output_dir / (args.date + '.md')} with {len(recommendations)} Japanese recommendations")
        return 0

    config = load_yaml(args.sources)
    state = load_state(args.state)
    candidates = collect_candidates(config, args.timeout)
    candidates = prefilter(candidates, state, args.max_candidates)
    if not candidates:
        raise RuntimeError("No new candidate articles found after fetching and deduplication")

    candidate_by_id = {candidate.key: candidate for candidate in candidates}
    if args.no_llm:
        recommendations = heuristic_recommendations(candidates, args.count)
    else:
        recommendations = call_llm(candidates, args.count)
    recommendations = [
        ensure_candidate_fields(item, candidate_by_id)
        for item in recommendations
        if item.get("id") in candidate_by_id or item.get("link")
    ][: args.count]

    if not recommendations:
        raise RuntimeError("No recommendations were selected")

    digest_path = args.output_dir / f"{args.date}.md"
    render_digest(digest_path, args.date, recommendations)
    update_seen(state, recommendations, args.date)
    save_state(args.state, state)
    update_digest_index(args.output_dir, args.index)
    if not args.skip_hot_topics:
        try:
            topics = generate_hot_topics(args.hot_topics_output, args.date, args.timeout, args.no_llm)
            print(f"Wrote {args.hot_topics_output} with {len(topics)} hot topics")
        except Exception as exc:
            print(f"Warning: failed to update Chinese hot topics: {exc}", file=sys.stderr)
    if not args.skip_japanese:
        try:
            japanese_recommendations = generate_japanese_digest(
                args.date,
                args.japanese_state,
                args.japanese_output_dir,
                args.japanese_index,
                args.japanese_count,
                args.max_candidates,
                args.timeout,
                args.no_llm,
            )
            print(f"Wrote {args.japanese_output_dir / (args.date + '.md')} with {len(japanese_recommendations)} Japanese recommendations")
        except Exception as exc:
            print(f"Warning: failed to update Japanese recommendations: {exc}", file=sys.stderr)
    print(f"Wrote {digest_path} with {len(recommendations)} recommendations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
