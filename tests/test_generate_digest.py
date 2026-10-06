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

    def test_prefilter_skips_seen_candidates(self):
        seen = make_candidate("Alpha", 1)
        fresh = make_candidate("Beta", 1)
        selected = digest.prefilter([seen, fresh], {"seen": {seen.key: {}}}, max_candidates=5)
        self.assertEqual([item.key for item in selected], [fresh.key])

class ProvenanceTests(unittest.TestCase):
    def test_digest_index_uses_each_files_modification_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            digest_path = root / "2026-08-12.md"
            digest_path.write_text("# Test\n\n## 1. Story\n", encoding="utf-8")
            digest.update_digest_index(root, root / "index.json")
            index = digest.json.loads((root / "index.json").read_text(encoding="utf-8"))
            expected = dt.datetime.fromtimestamp(digest_path.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
            self.assertEqual(index["digests"][0]["updated_at"], expected)




class FetchOnlyTests(unittest.TestCase):
    def test_default_run_preserves_source_summary_without_model(self):
        candidate = make_candidate("Alpha", 1)
        candidate.summary = "The actual summary supplied by the feed."
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args = ["generate_digest.py", "--date", "2026-10-06", "--state", str(root / "seen.json"),
                    "--output-dir", str(root / "digests"), "--index", str(root / "index.json"),
                    "--skip-hot-topics", "--skip-japanese"]
            with mock.patch("sys.argv", args), mock.patch.object(digest, "collect_candidates", return_value=[candidate]):
                self.assertEqual(digest.main(), 0)
            content = (root / "digests/2026-10-06.md").read_text()
            self.assertIn(candidate.summary, content)
            self.assertIn(candidate.link, content)
            self.assertNotIn("Priority score", content)
            self.assertNotIn("teaching", content)
            self.assertFalse(hasattr(digest, "call_llm"))

    def test_same_day_refresh_retains_earlier_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "2026-10-06.md"
            first = make_candidate("Alpha", 1)
            second = make_candidate("Beta", 1)
            digest.render_digest(path, "2026-10-06", digest.raw_items([first], 1))
            digest.render_digest(path, "2026-10-06", digest.raw_items([second], 1))
            content = path.read_text()
            self.assertIn(first.link, content)
            self.assertIn(second.link, content)

    def test_japanese_fetch_preserves_summary_even_with_old_api_environment(self):
        candidate = make_candidate("NHK", 1)
        candidate.summary = "公開ソースの概要。"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(digest, "collect_candidates", return_value=[candidate]), mock.patch.dict(
                digest.os.environ, {"OPENAI_API_KEY": "unused", "OPENAI_BASE_URL": "https://api.deepseek.com"}
            ):
                items = digest.generate_japanese_digest("2026-10-06", root / "seen.json", root / "news", root / "index.json", 80, 80, 10)
            self.assertEqual(items[0]["summary"], candidate.summary)
            self.assertIn(candidate.summary, (root / "news/2026-10-06.md").read_text())

    def test_hot_topics_use_only_fetched_fields(self):
        candidate = digest.HotTopicCandidate(1, "原始话题", "Baidu", "123", "https://top.baidu.com/")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(digest, "collect_hot_topics", return_value=[candidate]):
                topics = digest.generate_hot_topics(root / "latest.json", root / "topics", root / "index.json", "2026-10-06", 10)
            self.assertEqual(topics, [digest.dataclasses.asdict(candidate)])


if __name__ == "__main__":
    unittest.main()
