# News Radar

抓取公开 RSS 和新闻索引页的标题、来源、日期、链接及来源提供的摘要，直接在静态页面展示。英文、日文和国内热点均不调用大模型，无需 API 密钥，也不生成评分、难度、翻译或教学建议。不抓取文章全文。

## 本地使用

```bash
pip install -r requirements.txt
python scripts/generate_digest.py
python3 -m http.server 8000
```

打开 http://127.0.0.1:8000/ ，通过内容分类、日期和搜索查看条目。

摘要来自 RSS 或公开索引页，清除 HTML 并截取到 520 个字符。来源未提供摘要时，页面显示提示并保留原文链接。历史文稿没有保存原始摘要的条目也显示该提示，不使用旧的教学建议充当摘要。

## 抓取选项

```bash
python scripts/generate_digest.py --date 2026-10-06
python scripts/generate_digest.py --japanese-only
python scripts/generate_digest.py --topics-only
python scripts/generate_digest.py --count 80 --japanese-count 80 --max-candidates 80
```

默认每种语言最多保存 80 条，按来源轮流取条目，使用链接去重。`--no-llm` 仅为旧命令兼容参数；所有运行均不使用大模型。英文源配置在 `sources.yaml`，日文和国内热点源在抓取脚本中。单个来源失败不会丢弃其他来源的结果。

每日文稿位于 `digests/` 和 `japanese_digests/`，热点位于 `data/hot_topics/`。页面通过对应索引加载数据。历史文件保留，旧的评分和教学字段不在页面展示。

## 自动更新与发布

`.github/workflows/daily-digest.yml` 每天北京时间 08:10 和 20:10 抓取、提交数据并部署 GitHub Pages，也可手动运行。无需配置 OpenAI 或其他模型密钥。GitHub Pages 设置中选择 GitHub Actions 作为部署来源；`.github/workflows/pages.yml` 也支持推送后部署。


## API 费用与旧配置

目前自动任务仅访问公开新闻源和热点页面，不导入模型 SDK，不请求 OpenAI / DeepSeek 等模型服务，不会产生模型 API 用量。即使机器上还有旧的 API 环境变量，脚本也不会读取它们。GitHub Actions 中只需要时区配置，不需要模型密钥、模型名称或模型地址。

本仓库旧的 `OPENAI_API_KEY` secret 和 `OPENAI_BASE_URL` / `OPENAI_MODEL` variables 已从本仓库删除。删除仓库 secret 不等于在服务商处撤销密钥，也不影响其他项目使用同一个密钥。

两个工作流分别负责新闻抓取和静态部署。每天两次的新闻更新继续保留；若只想暂停抓取，可在 GitHub Actions 中停用 **Fetch News and Deploy**，现有站点和历史数据仍可浏览。

## 数据与维护

- `scripts/generate_digest.py`：并发抓取、链接去重、保存来源摘要和更新索引。
- `sources.yaml`：英文来源；脚本内的 `JAPANESE_SOURCES` 和 `HOT_TOPIC_SOURCES`：日文和热点来源。
- `index.html` / `app.js` / `styles.css`：静态列表、分类、日期与搜索，不调用外部模型。
- `requirements.txt`：仅保留新闻抓取、HTML 解析和配置读取依赖。
- `tests/`：抓取配置、去重、原始摘要、同日更新和热点字段检查。
- `digests/` / `japanese_digests/` / `data/hot_topics/`：历史内容。
- `data/*index.json`：页面索引；`data/seen_*.json`：抓取去重状态，不发布到站点。

同一天多次运行会保留先前条目并补充新条目，所以每日累计数量可能超过单次的 80 条上限。历史生成的评分、教学建议和英文热点改写保留在历史文件中供存档，页面不展示它们，也不继续生成它们。热点源通常只提供话题标题，页面展示标题、平台和来源榜单链接，不编造摘要。

部署工作流只发布页面、图标和展示数据，不上传抓取脚本、测试或本地环境。

验证项目：

```bash
python -m unittest discover -v
node --check app.js
```
