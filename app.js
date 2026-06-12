const state = {
  digests: [],
  japaneseDigests: [],
  selected: null,
  selectedJapanese: null,
  rawMarkdown: "",
  rawJapaneseMarkdown: "",
  articles: [],
  japaneseArticles: [],
  hotTopics: [],
  hotTopicsMeta: null,
  search: "",
  difficultyByView: {
    articles: "all",
    japanese: "all",
  },
  view: "articles",
};

const FILTERS_BY_VIEW = {
  articles: ["all", "B1", "B2", "C1", "C2"],
  japanese: ["all", "N4", "N3", "N2", "N1"],
};

const els = {
  list: document.querySelector("#digest-list"),
  count: document.querySelector("#digest-count"),
  title: document.querySelector("#page-title"),
  openMarkdown: document.querySelector("#open-markdown"),
  runWorkflow: document.querySelector("#run-workflow"),
  copyMarkdown: document.querySelector("#copy-markdown"),
  grid: document.querySelector("#article-grid"),
  empty: document.querySelector("#empty-state"),
  search: document.querySelector("#digest-search"),
  filtersBar: document.querySelector(".filters"),
  noResults: document.querySelector("#no-results"),
  viewSelect: document.querySelector("#section-select"),
  hotTopicsPanel: document.querySelector("#hot-topics-panel"),
  hotTopicsGrid: document.querySelector("#hot-topics-grid"),
  hotTopicsEmpty: document.querySelector("#hot-topics-empty"),
  hotTopicsDate: document.querySelector("#hot-topics-date"),
  japanesePanel: document.querySelector("#japanese-panel"),
  japaneseGrid: document.querySelector("#japanese-grid"),
  japaneseEmpty: document.querySelector("#japanese-empty"),
  historyPanel: document.querySelector(".history-panel"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseDigest(markdown) {
  const title = markdown.match(/^#\s+(.+)$/m)?.[1] ?? "Daily Recommendations";
  const sections = markdown.split(/^##\s+/m).slice(1);
  const articles = sections.map((section) => {
    const lines = section.trim().split("\n");
    const heading = lines.shift()?.replace(/^\d+\.\s*/, "").trim() ?? "Untitled";
    const fields = {};

    for (const line of lines) {
      const match = line.match(/^-\s+\*\*(.+?):\*\*\s*(.*)$/);
      if (!match) continue;
      fields[match[1].trim()] = match[2].trim();
    }

    return {
      title: heading,
      outlet: fields.Outlet,
      publicationDate: fields["Publication date"],
      link: fields.Link,
      topic: fields.Topic,
      articleType: fields["Article type"],
      tone: fields.Tone,
      teaching: fields["Why it is worth teaching"],
      viewerCare: fields["Why ordinary viewers may care"],
      languageValue: fields["Language value"],
      angle: fields["Suggested video angle"],
      expressions: (fields["Suggested expressions to teach"] || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      difficulty: fields["Estimated difficulty"],
      videoLength: fields["Estimated video length"],
      access: fields["Seems publicly accessible"],
      score: Number((fields["Priority score"] || "").match(/\d+/)?.[0] ?? 0),
    };
  });

  return { title, articles };
}

function matchesSearch(article) {
  const haystack = [
    article.title,
    article.outlet,
    article.topic,
    article.articleType,
    article.tone,
    article.teaching,
    article.languageValue,
    ...article.expressions,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(state.search.toLowerCase());
}

function visibleArticles(articles, view) {
  const difficulty = state.difficultyByView[view] || "all";
  return articles.filter((article) => {
    const difficultyMatch = difficulty === "all" || article.difficulty === difficulty;
    return difficultyMatch && matchesSearch(article);
  });
}

function visibleHotTopics() {
  if (!state.search) return state.hotTopics;
  const search = state.search.toLowerCase();
  return state.hotTopics.filter((topic) => {
    const haystack = [
      topic.chinese_topic,
      topic.official_english,
      topic.official_english_source,
      topic.why_hot,
      topic.share_angle,
      ...(topic.keywords || []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

function renderDigestList() {
  const digests = state.view === "japanese" ? state.japaneseDigests : state.digests;
  const selected = state.view === "japanese" ? state.selectedJapanese : state.selected;
  els.count.textContent = digests.length;
  els.list.innerHTML = digests
    .map(
      (digest) => `
        <button class="digest-item ${selected?.date === digest.date ? "is-active" : ""}" type="button" data-date="${escapeHtml(digest.date)}">
          <strong>${escapeHtml(digest.date)}</strong>
        </button>
      `,
    )
    .join("");
}

function syncHistoryPanelForViewport() {
  if (!els.historyPanel) return;
  els.historyPanel.open = !window.matchMedia("(max-width: 860px)").matches;
}

function renderView() {
  const isTopics = state.view === "topics";
  const isJapanese = state.view === "japanese";
  syncHeaderForView();
  els.viewSelect.value = state.view;
  els.filtersBar.hidden = isTopics;
  els.hotTopicsPanel.hidden = !isTopics;
  els.japanesePanel.hidden = !isJapanese;
  els.grid.hidden = isTopics || isJapanese;
  renderDigestList();
  renderFilters();
  els.empty.hidden = isTopics || isJapanese || (state.digests.length > 0 && state.articles.length > 0);
  els.noResults.hidden = true;
  if (isTopics) {
    renderHotTopics();
  } else if (isJapanese) {
    renderJapaneseArticles();
  } else {
    renderArticles();
  }
}

function syncHeaderForView() {
  if (state.view === "japanese") {
    els.title.textContent = state.selectedJapanese
      ? `${state.selectedJapanese.date} 日文精读推荐`
      : "请选择一篇日文推荐";
    els.openMarkdown.href = state.selectedJapanese?.file || "#";
    return;
  }
  if (state.view === "topics") {
    els.title.textContent = "今日国内热点话题";
    els.openMarkdown.href = "#";
    return;
  }
  els.title.textContent = state.selected ? `${state.selected.date} 每日精读推荐` : "请选择一篇每日推荐";
  els.openMarkdown.href = state.selected?.file || "#";
}

function getWorkflowUrl() {
  const configured = els.runWorkflow?.getAttribute("href");
  if (configured && configured !== "#") {
    return configured;
  }
  const host = window.location.hostname;
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (host.endsWith(".github.io") && parts.length > 0) {
    const owner = host.replace(".github.io", "");
    const repo = parts[0];
    return `https://github.com/${owner}/${repo}/actions/workflows/daily-digest.yml`;
  }
  return "https://github.com/";
}

function renderStats(articles) {
  return articles;
}

function renderFilters() {
  const filters = FILTERS_BY_VIEW[state.view] || [];
  if (!filters.length) {
    els.filtersBar.innerHTML = "";
    return;
  }
  const active = state.difficultyByView[state.view] || "all";
  els.filtersBar.innerHTML = filters
    .map(
      (filter) => `
        <button class="filter-chip ${active === filter ? "is-active" : ""}" type="button" data-filter="${escapeHtml(filter)}">
          ${filter === "all" ? "全部" : escapeHtml(filter)}
        </button>
      `,
    )
    .join("");
}

function renderArticles() {
  const articles = visibleArticles(state.articles, "articles");
  renderStats(articles);
  const hasDigest = state.digests.length > 0 && state.articles.length > 0;
  els.empty.hidden = state.view !== "articles" || hasDigest;
  els.noResults.hidden = state.view !== "articles" || !hasDigest || articles.length > 0;
  els.grid.innerHTML = articles
    .map(
      (article) => `
        <article class="article-card">
          <div class="card-top">
            <div>
              <p class="eyebrow">${escapeHtml(article.outlet || "Unknown outlet")}</p>
              <h3>${escapeHtml(article.title)}</h3>
            </div>
            <div class="score" title="Priority score">${escapeHtml(article.score || "-")}/10</div>
          </div>
          <div class="meta">
            <span class="pill">${escapeHtml(article.articleType || "article")}</span>
            <span class="pill tone">${escapeHtml(article.tone || "tone")}</span>
            <span class="pill difficulty">${escapeHtml(article.difficulty || "level")}</span>
            <span class="pill">${escapeHtml(article.videoLength || "video")}</span>
          </div>
          ${detail("Topic", article.topic)}
          ${detail("Why teach it", article.teaching)}
          ${detail("Viewer hook", article.viewerCare)}
          ${detail("Language value", article.languageValue)}
          ${detail("Video angle", article.angle)}
          <dl class="detail-block">
            <dt>Expressions</dt>
            <dd class="expressions">
              ${article.expressions.map((item) => `<span class="expression">${escapeHtml(item)}</span>`).join("")}
            </dd>
          </dl>
          ${detail("Access", article.access)}
          <a class="article-link" href="${escapeHtml(article.link)}" target="_blank" rel="noreferrer">阅读原文 →</a>
        </article>
      `,
    )
    .join("");
}

function renderJapaneseArticles() {
  const articles = visibleArticles(state.japaneseArticles, "japanese");
  const hasDigest = state.japaneseDigests.length > 0 && state.japaneseArticles.length > 0;
  els.japaneseEmpty.hidden = hasDigest;
  els.noResults.hidden = state.view !== "japanese" || !hasDigest || articles.length > 0;
  els.japaneseGrid.innerHTML = articles
    .map(
      (article) => `
        <article class="article-card">
          <div class="card-top">
            <div>
              <p class="eyebrow">${escapeHtml(article.outlet || "Unknown source")}</p>
              <h3>${escapeHtml(article.title)}</h3>
            </div>
            <div class="score" title="Priority score">${escapeHtml(article.score || "-")}/10</div>
          </div>
          <div class="meta">
            <span class="pill">${escapeHtml(article.articleType || "material")}</span>
            <span class="pill tone">${escapeHtml(article.tone || "tone")}</span>
            <span class="pill difficulty">${escapeHtml(article.difficulty || "level")}</span>
            <span class="pill">${escapeHtml(article.videoLength || "reading")}</span>
          </div>
          ${detail("Topic", article.topic)}
          ${detail("Why teach it", article.teaching)}
          ${detail("Learner hook", article.viewerCare)}
          ${detail("Language value", article.languageValue)}
          ${detail("Study angle", article.angle)}
          <dl class="detail-block">
            <dt>Expressions</dt>
            <dd class="expressions">
              ${article.expressions.map((item) => `<span class="expression">${escapeHtml(item)}</span>`).join("")}
            </dd>
          </dl>
          ${detail("Access", article.access)}
          <a class="article-link" href="${escapeHtml(article.link)}" target="_blank" rel="noreferrer">阅读原文 →</a>
        </article>
      `,
    )
    .join("");
}

function renderHotTopics() {
  const topics = visibleHotTopics();
  els.hotTopicsDate.textContent = state.hotTopicsMeta?.date
    ? `${state.hotTopicsMeta.date} 更新`
    : "待更新";
  els.hotTopicsEmpty.hidden = state.hotTopics.length > 0;
  els.hotTopicsGrid.hidden = state.hotTopics.length === 0;
  els.noResults.hidden = state.search === "" || topics.length > 0 || state.hotTopics.length === 0;
  els.hotTopicsGrid.innerHTML = topics
    .map(
      (topic) => `
        <article class="article-card hot-topic-card">
          <div class="card-top">
            <div>
              <p class="eyebrow">#${escapeHtml(topic.rank || "-")} ${escapeHtml(topic.platform || "Chinese web")}</p>
              <h3>${escapeHtml(topic.chinese_topic)}</h3>
            </div>
            <div class="score" title="Heat">${escapeHtml(topic.heat || "热")}</div>
          </div>
          ${detail("Official English / suggested wording", topic.official_english)}
          ${detail("Why it is hot", topic.why_hot)}
          ${detail("Share angle", topic.share_angle)}
          ${detail("Reference", topic.official_english_source)}
          ${
            Array.isArray(topic.keywords) && topic.keywords.length
              ? `<dl class="detail-block">
                  <dt>Keywords</dt>
                  <dd class="expressions">
                    ${topic.keywords.map((item) => `<span class="expression">${escapeHtml(item)}</span>`).join("")}
                  </dd>
                </dl>`
              : ""
          }
          ${topic.official_english_url ? `<a class="article-link" href="${escapeHtml(topic.official_english_url)}" target="_blank" rel="noreferrer">查看英文表述 →</a>` : ""}
        </article>
      `,
    )
    .join("");
}

function detail(label, value) {
  if (!value) return "";
  return `
    <dl class="detail-block">
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(value)}</dd>
    </dl>
  `;
}

async function loadDigest(digest) {
  state.selected = digest;
  renderDigestList();
  const response = await fetch(digest.file, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load ${digest.file}`);
  state.rawMarkdown = await response.text();
  const parsed = parseDigest(state.rawMarkdown);
  state.articles = parsed.articles;
  els.title.textContent = `${digest.date} 每日精读推荐`;
  els.openMarkdown.href = digest.file;
  renderView();
}

async function loadJapaneseDigest(digest) {
  state.selectedJapanese = digest;
  renderDigestList();
  const response = await fetch(digest.file, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load ${digest.file}`);
  state.rawJapaneseMarkdown = await response.text();
  const parsed = parseDigest(state.rawJapaneseMarkdown);
  state.japaneseArticles = parsed.articles;
  renderView();
}

async function loadHotTopics() {
  try {
    const response = await fetch("data/chinese_hot_topics.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Hot topics not found");
    const data = await response.json();
    state.hotTopicsMeta = data;
    state.hotTopics = Array.isArray(data.topics) ? data.topics : [];
  } catch (error) {
    console.warn(error);
    state.hotTopicsMeta = null;
    state.hotTopics = [];
  }
  if (state.view === "topics") renderHotTopics();
}

async function loadIndex() {
  try {
    const response = await fetch("data/digests_index.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Digest index not found");
    const data = await response.json();
    state.digests = Array.isArray(data.digests) ? data.digests : [];
    renderDigestList();
    if (state.digests.length > 0) {
      await loadDigest(state.digests[0]);
    } else {
      renderView();
    }
  } catch (error) {
    console.error(error);
    els.empty.hidden = false;
  }
}

async function loadJapaneseIndex() {
  try {
    const response = await fetch("data/japanese_digests_index.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Japanese digest index not found");
    const data = await response.json();
    state.japaneseDigests = Array.isArray(data.digests) ? data.digests : [];
    if (state.japaneseDigests.length > 0) {
      await loadJapaneseDigest(state.japaneseDigests[0]);
    } else if (state.view === "japanese") {
      renderView();
    }
  } catch (error) {
    console.warn(error);
    state.japaneseDigests = [];
    if (state.view === "japanese") renderView();
  }
}

els.list.addEventListener("click", (event) => {
  const button = event.target.closest("[data-date]");
  if (!button) return;
  const digests = state.view === "japanese" ? state.japaneseDigests : state.digests;
  const digest = digests.find((item) => item.date === button.dataset.date);
  if (!digest) return;
  if (state.view === "japanese") {
    loadJapaneseDigest(digest);
  } else {
    loadDigest(digest);
  }
});

els.search.addEventListener("input", (event) => {
  state.search = event.target.value;
  renderView();
});

els.filtersBar.addEventListener("click", (event) => {
  const button = event.target.closest("[data-filter]");
  if (!button) return;
  state.difficultyByView[state.view] = button.dataset.filter;
  renderFilters();
  if (state.view === "japanese") {
    renderJapaneseArticles();
  } else {
    renderArticles();
  }
});

els.viewSelect.addEventListener("change", (event) => {
  state.view = event.target.value;
  renderView();
});

els.copyMarkdown.addEventListener("click", async () => {
  if (state.view === "topics") return;
  const markdown = state.view === "japanese" ? state.rawJapaneseMarkdown : state.rawMarkdown;
  if (!markdown) return;
  await navigator.clipboard.writeText(markdown);
  els.copyMarkdown.textContent = "✓";
  window.setTimeout(() => {
    els.copyMarkdown.textContent = "⧉";
  }, 1200);
});

loadHotTopics();
loadIndex();
loadJapaneseIndex();
els.runWorkflow.href = getWorkflowUrl();
syncHistoryPanelForViewport();
window.addEventListener("resize", syncHistoryPanelForViewport);
