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
