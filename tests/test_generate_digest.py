import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import generate_digest as digest


def make_candidate(outlet: str, index: int, date: str = "2026-08-12") -> digest.Candidate:
    return digest.Candidate(
        title=f"{outlet} story {index}",
        outlet=outlet,
        link=f"https://{outlet.lower()}.example/story-{index}",
        source_name=outlet,
        publication_date=date,
        summary="A useful public-interest summary.",
        default_topic="Public interest",
        article_type_hint="feature",
        public_access="likely public",
    )


class ConfigurationTests(unittest.TestCase):
    def test_default_sources_are_valid_and_diverse(self):
        config = digest.load_yaml(digest.DEFAULT_SOURCES)
        sources = digest.validate_sources(config)
        active_outlets = {
            source.get("outlet", source["name"])
            for source in sources
            if source.get("enabled", True)
        }
        self.assertGreaterEqual(len(active_outlets), 20)

    def test_validate_sources_rejects_duplicates_and_bad_types(self):
        duplicate = {
            "sources": [
                {"name": "Same", "url": "https://one.example/feed"},
                {"name": "Same", "url": "https://two.example/feed"},
            ]
        }
        with self.assertRaisesRegex(ValueError, "Duplicate source name"):
            digest.validate_sources(duplicate)

        with self.assertRaisesRegex(ValueError, "Unsupported source_type"):
            digest.validate_sources(
                {"sources": [{"name": "Bad", "url": "https://bad.example", "source_type": "api"}]}
            )

    def test_digest_date_rejects_noncanonical_and_path_values(self):
        self.assertEqual(digest.validate_digest_date("2026-08-12"), "2026-08-12")
        for value in ("2026-8-12", "2026-02-30", "../../outside"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                digest.validate_digest_date(value)

    def test_transient_fetch_errors_are_retried(self):
        response = mock.Mock(status_code=200)
        with mock.patch.object(
            digest.requests,
            "get",
            side_effect=[digest.requests.ConnectionError("temporary"), response],
        ) as get_mock:
            with mock.patch.object(digest.time, "sleep") as sleep_mock:
                result = digest.get_with_retry("https://example.com/feed", 10, "TestAgent")
        self.assertIs(result, response)
        self.assertEqual(get_mock.call_count, 2)
        sleep_mock.assert_called_once_with(0.4)


class DiversityTests(unittest.TestCase):
    def test_prefilter_round_robins_outlets(self):
        candidates = [
            *[make_candidate("Alpha", index) for index in range(8)],
            *[make_candidate("Beta", index) for index in range(8)],
            *[make_candidate("Gamma", index) for index in range(8)],
        ]
        selected = digest.prefilter(candidates, {"seen": {}}, max_candidates=6)
        self.assertEqual(len(selected), 6)
        self.assertEqual({item.outlet for item in selected[:3]}, {"Alpha", "Beta", "Gamma"})
        self.assertEqual({item.outlet for item in selected[3:]}, {"Alpha", "Beta", "Gamma"})

    def test_finalize_recommendations_locks_provenance_and_fills_diversely(self):
        alpha_one = make_candidate("Alpha", 1)
        alpha_two = make_candidate("Alpha", 2)
        beta = make_candidate("Beta", 1)
        gamma = make_candidate("Gamma", 1)
        candidates = [alpha_one, alpha_two, beta, gamma]
        model_items = [
            {
                "id": alpha_one.key,
                "title": "Invented title",
                "outlet": "Invented outlet",
                "link": "javascript:alert(1)",
                "priority_score": 99,
            },
            {"id": alpha_two.key},
            {"id": "unknown", "link": "https://invented.example"},
        ]

        finalized = digest.finalize_recommendations(
            model_items,
            candidates,
            count=3,
            fallback_builder=digest.heuristic_recommendations,
        )

        self.assertEqual(len(finalized), 3)
        self.assertEqual({item["outlet"] for item in finalized}, {"Alpha", "Beta", "Gamma"})
        first = finalized[0]
        self.assertEqual(first["title"], alpha_one.title)
        self.assertEqual(first["link"], alpha_one.link)
        self.assertEqual(first["priority_score"], 10)

    def test_prefilter_skips_seen_candidates(self):
        seen = make_candidate("Alpha", 1)
        fresh = make_candidate("Beta", 1)
        selected = digest.prefilter([seen, fresh], {"seen": {seen.key: {}}}, max_candidates=5)
        self.assertEqual([item.key for item in selected], [fresh.key])

    def test_heuristic_topic_keywords_match_whole_words(self):
        candidate = make_candidate("Alpha", 1)
        candidate.title = "Amid drought, rivers are drying up"
        candidate.default_topic = "Environment and climate"
        recommendation = digest.heuristic_recommendations([candidate], 1)[0]
        self.assertEqual(recommendation["topic"], "Environment and climate")

    def test_finalize_relaxes_cap_when_an_outlet_has_too_few_items(self):
        candidates = [
            make_candidate("Alpha", 1),
            make_candidate("Alpha", 2),
            make_candidate("Alpha", 3),
            make_candidate("Beta", 1),
        ]
        finalized = digest.finalize_recommendations(
            [],
            candidates,
            count=4,
            fallback_builder=digest.heuristic_recommendations,
        )
        self.assertEqual(len(finalized), 4)
        self.assertEqual({item["outlet"] for item in finalized}, {"Alpha", "Beta"})


class ProvenanceTests(unittest.TestCase):
    def test_hot_topic_provenance_and_official_url_are_allowlisted(self):
        candidate = digest.HotTopicCandidate(1, "测试话题", "Baidu", "hot", "https://top.baidu.com/")
        topics = [
            {
                "rank": 1,
                "chinese_topic": "被改写的话题",
                "platform": "Fake",
                "source_url": "javascript:alert(1)",
                "official_english": "Suggested headline",
                "official_english_source": "Fake outlet",
                "official_english_url": "https://fake.example/story",
            }
        ]
        result = digest.ensure_hot_topic_fields(topics, [candidate], [
            {"outlet": "China Daily", "title": "Official", "url": "https://official.example/story"}
        ])
        self.assertEqual(result[0]["chinese_topic"], candidate.chinese_topic)
        self.assertEqual(result[0]["platform"], candidate.platform)
        self.assertEqual(result[0]["source_url"], candidate.source_url)
        self.assertEqual(result[0]["official_english_url"], "")
        self.assertEqual(result[0]["official_english_source"], "Suggested wording")

    def test_digest_index_uses_each_files_modification_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            digest_path = root / "2026-08-12.md"
            digest_path.write_text("# Test\n\n## 1. Story\n", encoding="utf-8")
            digest.update_digest_index(root, root / "index.json")
            index = digest.json.loads((root / "index.json").read_text(encoding="utf-8"))
            expected = dt.datetime.fromtimestamp(digest_path.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
            self.assertEqual(index["digests"][0]["updated_at"], expected)


if __name__ == "__main__":
    unittest.main()
