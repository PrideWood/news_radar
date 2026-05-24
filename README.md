# News Radar: Daily English Close-Reading Digest

This project generates one Markdown digest per day under `digests/YYYY-MM-DD.md`. Each digest recommends 5-10 publicly accessible English news, feature, or magazine-style articles that are suitable for short close-reading videos.

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

The reader loads `data/digests_index.json`, lists available daily digests, renders each recommendation as a card, and supports search plus B1/B2/C1 filtering. The digest generator updates the index automatically whenever it writes a new Markdown file.

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

The workflow at `.github/workflows/daily-digest.yml` runs every day at `01:00 UTC` and can also be started manually with `workflow_dispatch`.

Required repository secret:

- `OPENAI_API_KEY`

Optional repository variable:

- `OPENAI_MODEL`, defaults to `gpt-4o-mini`
- `OPENAI_BASE_URL`, for DeepSeek or other OpenAI-compatible providers

The workflow commits new files in `digests/` and updates `data/seen_articles.json` for deduplication plus `data/digests_index.json` for the frontend reader.

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
