# News Radar: Daily English Close-Reading Digest

This project generates one Markdown digest per day under `digests/YYYY-MM-DD.md`. Each digest recommends 5-10 publicly accessible English news, feature, or magazine-style articles that are suitable for short close-reading videos. It can also generate a separate Japanese close-reading digest under `japanese_digests/YYYY-MM-DD.md`.

The generator uses RSS feeds or public index pages for article metadata. It stores only metadata, links, short public summaries/previews, and teaching suggestions. It does not download or store full copyrighted article text.

## What It Produces

Each recommendation includes:

- title, outlet, publication date, and link
- topic, article type, and tone
- why it is worth teaching
- why ordinary viewers may care
- language value
- suggested video angle
- 3-5 expressions to teach
- estimated CEFR difficulty and video length
- public-access estimate
- priority score from 1 to 10

The generator also writes `data/chinese_hot_topics.json` with three Chinese internet hot topics for the day. Each topic includes the Chinese topic text, a neutral official-style English wording or matched official English headline when available, a short reason it is hot, a share angle, and keywords for later AI-assisted content preparation.

Japanese recommendations use public Japanese-language metadata from news, technology, internet culture, and public-information sources. They are selected for language-learning value across JLPT-style levels N4-N1 and are not limited to hard news.

The daily mix aims to include short news, human-interest or uplifting stories, a science or technology explainer, an education/youth/culture story, a serious public-interest story, and one surprising wildcard.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Set your OpenAI API key:

```bash
export OPENAI_API_KEY="your_api_key_here"
```

Optionally set the model:

```bash
export OPENAI_MODEL="gpt-4o-mini"
```

For DeepSeek or another OpenAI-compatible provider, also set a base URL:

```bash
export OPENAI_API_KEY="your_deepseek_key_here"
export OPENAI_BASE_URL="https://api.deepseek.com"
export OPENAI_MODEL="deepseek-chat"
```

Generate today's digest:

```bash
python scripts/generate_digest.py
```

Generate a specific date:

```bash
python scripts/generate_digest.py --date 2026-05-24
```

Run a local smoke test without an LLM:

```bash
python scripts/generate_digest.py --no-llm
```

Update only the Japanese close-reading data:

```bash
python scripts/generate_digest.py --japanese-only
```

Update only the Chinese hot topics data:

```bash
python scripts/generate_digest.py --topics-only
```

The `--no-llm` mode is for development only. In normal use, the LLM is used only for scoring, selection, and teaching suggestions from metadata and short public excerpts.

## Frontend Reader

Start a local static server from the project root:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://127.0.0.1:8000/
```

The reader loads `data/digests_index.json`, lists available daily English digests, renders each recommendation as a card, and supports search plus B1/B2/C1/C2 filtering. It also loads `data/chinese_hot_topics.json` in the "国内热点话题" view and `data/japanese_digests_index.json` in the "日文精读推荐" view, where filtering uses N4/N3/N2/N1. The digest generator updates indexes automatically whenever it writes new Markdown files.

## GitHub Pages

This project includes a static GitHub Pages workflow at `.github/workflows/pages.yml`.

After pushing the repository to GitHub:

1. Open the repository on GitHub.
2. Go to `Settings` -> `Pages`.
3. Under `Build and deployment`, set `Source` to `GitHub Actions`.
4. Run the `Deploy GitHub Pages` workflow manually, or push to `main`.

Your site will be available at:

```text
https://<your-github-username>.github.io/news_radar/
```

If you add a custom domain in `Settings` -> `Pages`, GitHub will serve the same static reader from that domain. The API key is not exposed to the frontend because it stays in GitHub Actions secrets.

For a custom subdomain such as `news.example.com`, create a DNS `CNAME` record pointing to:

```text
<your-github-username>.github.io
```

## GitHub Actions

The workflow at `.github/workflows/daily-digest.yml` runs every day at `08:10` and `20:10` in Beijing/Shanghai time, and can also be started manually with `workflow_dispatch`.
The generator uses the `Asia/Shanghai` date by default, so scheduled and manual runs both create the digest for the expected local day.
After generating and committing the new digest, it deploys GitHub Pages directly so the site updates without manually running the Pages workflow.

Required repository secret:

- `OPENAI_API_KEY`

Optional repository variable:

- `OPENAI_MODEL`, defaults to `gpt-4o-mini`
- `OPENAI_BASE_URL`, for DeepSeek or other OpenAI-compatible providers
- `NEWS_RADAR_TIMEZONE`, defaults to `Asia/Shanghai`

The workflow commits new files in `digests/` and `japanese_digests/`, updates `data/seen_articles.json` and `data/seen_japanese_items.json` for deduplication, updates both frontend indexes, and writes `data/chinese_hot_topics.json` for the hot-topic view. If the English digest for the day already exists, the workflow refreshes the hot-topic and Japanese data.

## Customizing Sources

Edit `sources.yaml`.

For RSS feeds, add:

```yaml
- name: Example Source
  outlet: Example
  url: https://example.com/rss
  source_type: rss
  default_topic: Culture and everyday life
  article_type_hint: feature
  public_access: likely public
```

For a public index page, add selectors:

```yaml
- name: Example Index
  outlet: Example
  url: https://example.com/latest
  source_type: html
  item_selector: article
  title_selector: h2
  link_selector: a[href]
  summary_selector: p
  default_topic: Public-interest stories
```

You can pause a source with:

```yaml
enabled: false
```

## Deduplication

Recommended articles are recorded in `data/seen_articles.json`. The generator skips previously recommended URLs so the same article is not selected repeatedly. The state file is capped automatically to keep the repository small.

## Selection Criteria

The system favors articles that are:

- publicly accessible or have a meaningful public preview
- written in clear, high-quality English
- useful for close reading in a short video
- interesting to ordinary viewers
- rich in vocabulary, sentence structure, narrative technique, or explanatory value
- positive, engaging, thought-provoking, or practically useful

It avoids celebrity gossip, pure market updates, highly technical specialist reports, strongly partisan opinion pieces, graphic crime stories without public-interest value, mostly paywalled articles, repetitive breaking news, and lists that feel too negative or heavy.
