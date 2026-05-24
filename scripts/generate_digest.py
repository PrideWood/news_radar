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
        estimated_difficulty (B1/B2/C1), estimated_video_length (5 min/10 min/15 min),
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


def update_digest_index(digest_dir: Path, index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for digest_path in sorted(digest_dir.glob("*.md"), reverse=True):
        text = digest_path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        item_count = len(re.findall(r"^##\s+\d+\.", text, flags=re.MULTILINE))
        entries.append(
            {
                "date": digest_path.stem,
                "file": f"digests/{digest_path.name}",
                "title": title_match.group(1).strip() if title_match else digest_path.stem,
                "item_count": item_count,
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            }
        )
    with index_path.open("w", encoding="utf-8") as handle:
        json.dump({"digests": entries}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIGEST_DIR)
    parser.add_argument("--index", type=Path, default=DEFAULT_DIGEST_INDEX)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic fallback for local smoke tests.")
    args = parser.parse_args()

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
    print(f"Wrote {digest_path} with {len(recommendations)} recommendations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
