const state = {
  digests: [],
  selected: null,
  rawMarkdown: "",
  articles: [],
  search: "",
  difficulty: "all",
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
  statItems: document.querySelector("#stat-items"),
  statDate: document.querySelector("#stat-date"),
  statAverage: document.querySelector("#stat-average"),
  filters: document.querySelectorAll(".filter-chip"),
  noResults: document.querySelector("#no-results"),
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

function visibleArticles() {
  return state.articles.filter((article) => {
    const difficultyMatch = state.difficulty === "all" || article.difficulty === state.difficulty;
    return difficultyMatch && matchesSearch(article);
  });
}

function renderDigestList() {
  els.count.textContent = state.digests.length;
  els.list.innerHTML = state.digests
    .map(
      (digest) => `
        <button class="digest-item ${state.selected?.date === digest.date ? "is-active" : ""}" type="button" data-date="${escapeHtml(digest.date)}">
          <strong>${escapeHtml(digest.date)}</strong>
          <span>${escapeHtml(digest.item_count)} 篇推荐</span>
        </button>
      `,
    )
    .join("");
}

function getWorkflowUrl() {
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
  const average = articles.length
    ? (articles.reduce((sum, article) => sum + article.score, 0) / articles.length).toFixed(1)
    : "-";
  els.statItems.textContent = String(articles.length);
  els.statDate.textContent = state.selected?.date ?? "-";
  els.statAverage.textContent = average;
}

function renderArticles() {
  const articles = visibleArticles();
  renderStats(articles);
  const hasDigest = state.digests.length > 0 && state.articles.length > 0;
  els.empty.hidden = hasDigest;
  els.noResults.hidden = !hasDigest || articles.length > 0;
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
  renderArticles();
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
      renderArticles();
    }
  } catch (error) {
    console.error(error);
    els.empty.hidden = false;
  }
}

els.list.addEventListener("click", (event) => {
  const button = event.target.closest("[data-date]");
  if (!button) return;
  const digest = state.digests.find((item) => item.date === button.dataset.date);
  if (digest) loadDigest(digest);
});

els.search.addEventListener("input", (event) => {
  state.search = event.target.value;
  renderArticles();
});

els.filters.forEach((button) => {
  button.addEventListener("click", () => {
    state.difficulty = button.dataset.filter;
    els.filters.forEach((item) => item.classList.toggle("is-active", item === button));
    renderArticles();
  });
});

els.copyMarkdown.addEventListener("click", async () => {
  if (!state.rawMarkdown) return;
  await navigator.clipboard.writeText(state.rawMarkdown);
  els.copyMarkdown.textContent = "✓";
  window.setTimeout(() => {
    els.copyMarkdown.textContent = "⧉";
  }, 1200);
});

loadIndex();
els.runWorkflow.href = getWorkflowUrl();
