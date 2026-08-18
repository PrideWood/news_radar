const state = {
  digests: [],
  japaneseDigests: [],
  hotTopicDigests: [],
  selected: null,
  selectedJapanese: null,
  selectedHotTopics: null,
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
  loadVersion: {
    articles: 0,
    japanese: 0,
    topics: 0,
  },
  view: "articles",
  page: window.location.hash === "#statistics" ? "statistics" : "reader",
  articleMarks: {},
  statistics: {
    startDate: "",
    endDate: "",
    language: "all",
    articles: [],
    loading: false,
    requestVersion: 0,
  },
};

const ARTICLE_MARKS_STORAGE_KEY = "news-radar:article-marks:v1";
const statisticsDigestCache = new Map();

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
  historyTitle: document.querySelector("#history-title"),
  pageEyebrow: document.querySelector("#page-eyebrow"),
  statisticsToggle: document.querySelector("#statistics-toggle"),
  readerOnlyActions: document.querySelectorAll(".reader-only-action"),
  contentControls: document.querySelector(".content-controls"),
  statisticsPanel: document.querySelector("#statistics-panel"),
  statisticsStartDate: document.querySelector("#statistics-start-date"),
  statisticsEndDate: document.querySelector("#statistics-end-date"),
  statisticsLanguage: document.querySelector("#statistics-language"),
  statisticsLoading: document.querySelector("#statistics-loading"),
  statisticsEmpty: document.querySelector("#statistics-empty"),
  statisticsContent: document.querySelector("#statistics-content"),
  statArticleCount: document.querySelector("#stat-article-count"),
  statDayCount: document.querySelector("#stat-day-count"),
  statAverageScore: document.querySelector("#stat-average-score"),
  statVideoCount: document.querySelector("#stat-video-count"),
  statCompletionRate: document.querySelector("#stat-completion-rate"),
  statPendingCount: document.querySelector("#stat-pending-count"),
  statSourceCount: document.querySelector("#stat-source-count"),
  statCefrCount: document.querySelector("#stat-cefr-count"),
  sourceChart: document.querySelector("#source-chart"),
  scoreChart: document.querySelector("#score-chart"),
  difficultyChart: document.querySelector("#difficulty-chart"),
  videoHeatmap: document.querySelector("#video-heatmap"),
};

state.articleMarks = loadArticleMarks();

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function safeHref(value, allowRelative = false) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw, window.location.href);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    const isRelative = !/^[a-z][a-z\d+.-]*:/i.test(raw) && !raw.startsWith("//");
    return allowRelative && isRelative ? raw : parsed.href;
  } catch {
    return "";
  }
}

function loadArticleMarks() {
  try {
    const saved = window.localStorage.getItem(ARTICLE_MARKS_STORAGE_KEY);
    const parsed = saved ? JSON.parse(saved) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (error) {
    console.warn("Unable to load article marks", error);
    return {};
  }
}

function saveArticleMarks() {
  try {
    window.localStorage.setItem(ARTICLE_MARKS_STORAGE_KEY, JSON.stringify(state.articleMarks));
  } catch (error) {
    console.warn("Unable to save article marks", error);
  }
}

function makeArticleId(article) {
  const link = String(article.link || "").trim();
  if (link) return link;
  return [article.language || "article", article.digestDate || article.publicationDate || "", article.title || ""]
    .join("|")
    .toLowerCase();
}

function isArticleCompleted(article) {
  return Boolean(state.articleMarks[article.id || makeArticleId(article)]);
}

function toggleArticleCompleted(article) {
  const id = article.id || makeArticleId(article);
  if (state.articleMarks[id]) {
    delete state.articleMarks[id];
  } else {
    state.articleMarks[id] = {
      title: article.title,
      outlet: article.outlet,
      digestDate: article.digestDate,
      language: article.language,
      markedAt: new Date().toISOString(),
    };
  }
  saveArticleMarks();
  renderView();
}

function externalLink(value, label) {
  const href = safeHref(value);
  if (!href) return "";
  return `<a class="article-link" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function articleFooter(article, linkLabel = "阅读原文 →") {
  const completed = isArticleCompleted(article);
  return `
    <div class="article-footer">
      ${externalLink(article.link, linkLabel)}
      <button
        class="completion-button ${completed ? "is-complete" : ""}"
        type="button"
        data-article-id="${escapeHtml(article.id)}"
        aria-pressed="${completed}"
      >
        <span aria-hidden="true">${completed ? "✓" : "○"}</span>
        ${completed ? "已精读 · 已制作视频" : "标记为已精读"}
      </button>
    </div>
  `;
}

function parseDigest(markdown, digestDate = "", language = "english") {
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

    const article = {
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
      digestDate,
      language,
    };
    article.id = makeArticleId(article);
    return article;
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
  const digests =
    state.view === "topics"
      ? state.hotTopicDigests
      : state.view === "japanese"
        ? state.japaneseDigests
        : state.digests;
  const selected =
    state.view === "topics"
      ? state.selectedHotTopics
      : state.view === "japanese"
        ? state.selectedJapanese
        : state.selected;
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
  const isStatistics = state.page === "statistics";
  document.body.classList.toggle("statistics-view", isStatistics);
  els.statisticsPanel.hidden = !isStatistics;
  els.readerOnlyActions.forEach((element) => {
    element.hidden = isStatistics;
  });
  els.statisticsToggle.textContent = isStatistics ? "返回文章" : "数据统计";
  els.statisticsToggle.href = isStatistics ? "#" : "#statistics";

  if (isStatistics) {
    els.pageEyebrow.textContent = "Insights Dashboard";
    els.title.textContent = "数据统计";
    els.contentControls.hidden = true;
    els.hotTopicsPanel.hidden = true;
    els.japanesePanel.hidden = true;
    els.grid.hidden = true;
    els.empty.hidden = true;
    els.noResults.hidden = true;
    renderStatistics();
    return;
  }

  const isTopics = state.view === "topics";
  const isJapanese = state.view === "japanese";
  els.pageEyebrow.textContent = "Daily Recommendations";
  els.contentControls.hidden = false;
  syncHeaderForView();
  syncSidebarForView();
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

function syncSidebarForView() {
  els.historyPanel.hidden = false;
  if (state.view === "topics") {
    els.historyTitle.textContent = "热点日期";
    return;
  }
  if (state.view === "japanese") {
    els.historyTitle.textContent = "日文文稿";
    return;
  }
  els.historyTitle.textContent = "每日文稿";
}

function syncHeaderForView() {
  if (state.view === "japanese") {
    els.title.textContent = state.selectedJapanese
      ? `${state.selectedJapanese.date} 日文精读推荐`
      : "请选择一篇日文推荐";
    els.openMarkdown.href = safeHref(state.selectedJapanese?.file, true) || "#";
    return;
  }
  if (state.view === "topics") {
    els.title.textContent = state.hotTopicsMeta?.date
      ? `${state.hotTopicsMeta.date} 国内热点话题`
      : "请选择一组国内热点话题";
    els.openMarkdown.href = safeHref(state.selectedHotTopics?.file || "data/chinese_hot_topics.json", true) || "#";
    return;
  }
  els.title.textContent = state.selected ? `${state.selected.date} 每日精读推荐` : "请选择一篇每日推荐";
  els.openMarkdown.href = safeHref(state.selected?.file, true) || "#";
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

function dateFromIso(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

function isoFromDate(date) {
  return date.toISOString().slice(0, 10);
}

function shiftIsoDate(value, days) {
  const date = dateFromIso(value);
  if (!date) return value;
  date.setUTCDate(date.getUTCDate() + days);
  return isoFromDate(date);
}

function availableDigestDates() {
  return [...state.digests, ...state.japaneseDigests]
    .map((digest) => digest.date)
    .filter(Boolean)
    .sort();
}

function syncStatisticsDateRange() {
  const dates = availableDigestDates();
  if (!dates.length) return;
  const earliest = dates[0];
  const latest = dates[dates.length - 1];
  els.statisticsStartDate.min = earliest;
  els.statisticsStartDate.max = latest;
  els.statisticsEndDate.min = earliest;
  els.statisticsEndDate.max = latest;

  if (!state.statistics.endDate) state.statistics.endDate = latest;
  if (!state.statistics.startDate) {
    const lastThirtyDays = shiftIsoDate(latest, -29);
    state.statistics.startDate = lastThirtyDays < earliest ? earliest : lastThirtyDays;
  }
  els.statisticsStartDate.value = state.statistics.startDate;
  els.statisticsEndDate.value = state.statistics.endDate;
  els.statisticsLanguage.value = state.statistics.language;
}

function digestsForStatistics() {
  const { startDate, endDate, language } = state.statistics;
  const entries = [];
  if (language === "all" || language === "english") {
    entries.push(...state.digests.map((digest) => ({ ...digest, language: "english" })));
  }
  if (language === "all" || language === "japanese") {
    entries.push(...state.japaneseDigests.map((digest) => ({ ...digest, language: "japanese" })));
  }
  return entries.filter((digest) => digest.date >= startDate && digest.date <= endDate);
}

async function fetchDigestArticles(digest) {
  const cacheKey = `${digest.language}:${digest.file}`;
  if (statisticsDigestCache.has(cacheKey)) return statisticsDigestCache.get(cacheKey);
  const response = await fetch(digest.file, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load ${digest.file}`);
  const markdown = await response.text();
  const articles = parseDigest(markdown, digest.date, digest.language).articles;
  statisticsDigestCache.set(cacheKey, articles);
  return articles;
}

async function loadStatistics() {
  if (!state.statistics.startDate || !state.statistics.endDate) return;
  const requestVersion = ++state.statistics.requestVersion;
  state.statistics.loading = true;
  renderStatistics();
  const digests = digestsForStatistics();
  const results = await Promise.allSettled(digests.map(fetchDigestArticles));
  if (requestVersion !== state.statistics.requestVersion) return;
  state.statistics.articles = results.flatMap((result) => (result.status === "fulfilled" ? result.value : []));
  state.statistics.loading = false;
  const failedCount = results.filter((result) => result.status === "rejected").length;
  if (failedCount) console.warn(`${failedCount} digest files could not be included in statistics`);
  renderStatistics();
}

function renderSourceChart(articles) {
  const counts = new Map();
  articles.forEach((article) => {
    const source = article.outlet || "未知来源";
    counts.set(source, (counts.get(source) || 0) + 1);
  });
  const sources = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const maxCount = Math.max(1, ...sources.map(([, count]) => count));
  els.statSourceCount.textContent = `${sources.length} 个来源`;
  els.sourceChart.innerHTML = sources
    .map(
      ([source, count]) => `
        <div class="bar-row">
          <div class="bar-label"><span title="${escapeHtml(source)}">${escapeHtml(source)}</span><strong>${count}</strong></div>
          <div class="bar-track" aria-label="${escapeHtml(source)}：${count} 篇">
            <span style="width: ${(count / maxCount) * 100}%"></span>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderScoreChart(articles) {
  const counts = Array(11).fill(0);
  articles.forEach((article) => {
    if (article.score >= 1 && article.score <= 10) counts[article.score] += 1;
  });
  const maxCount = Math.max(1, ...counts);
  els.scoreChart.innerHTML = counts
    .slice(1)
    .map(
      (count, index) => `
        <div class="score-column" title="${index + 1} 分：${count} 篇">
          <strong>${count || ""}</strong>
          <div class="score-bar-track"><span style="height: ${(count / maxCount) * 100}%"></span></div>
          <small>${index + 1}</small>
        </div>
      `,
    )
    .join("");
}

function renderDifficultyChart(articles) {
  const levels = ["B1", "B2", "C1", "C2"];
  const englishArticles = articles.filter((article) => article.language === "english");
  const counts = levels.map(
    (level) => englishArticles.filter((article) => article.difficulty === level).length,
  );
  const maxCount = Math.max(1, ...counts);
  const total = counts.reduce((sum, count) => sum + count, 0);
  els.statCefrCount.textContent = `${total} 篇英文文章`;
  els.difficultyChart.innerHTML = levels
    .map((level, index) => {
      const count = counts[index];
      const percentage = total ? Math.round((count / total) * 100) : 0;
      return `
        <div class="difficulty-column" title="${level}：${count} 篇，占 ${percentage}%">
          <strong>${count}</strong>
          <div class="difficulty-bar-track"><span style="height: ${(count / maxCount) * 100}%"></span></div>
          <small>${level}</small>
          <em>${percentage}%</em>
        </div>
      `;
    })
    .join("");
}

function monthName(date) {
  return `${date.getUTCFullYear()} 年 ${date.getUTCMonth() + 1} 月`;
}

function renderVideoHeatmap(articles) {
  const completedDates = new Set();
  const totalByDate = new Map();
  articles.forEach((article) => {
    totalByDate.set(article.digestDate, (totalByDate.get(article.digestDate) || 0) + 1);
    if (isArticleCompleted(article)) completedDates.add(article.digestDate);
  });
  const start = dateFromIso(state.statistics.startDate);
  const end = dateFromIso(state.statistics.endDate);
  if (!start || !end) {
    els.videoHeatmap.innerHTML = "";
    return;
  }

  const months = [new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), 1))];

  els.videoHeatmap.innerHTML = months
    .map((month) => {
      const year = month.getUTCFullYear();
      const monthIndex = month.getUTCMonth();
      const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
      const leadingBlanks = (new Date(Date.UTC(year, monthIndex, 1)).getUTCDay() + 6) % 7;
      const cells = Array.from({ length: leadingBlanks }, () => '<span class="heatmap-day is-blank"></span>');
      for (let day = 1; day <= daysInMonth; day += 1) {
        const date = isoFromDate(new Date(Date.UTC(year, monthIndex, day)));
        const inRange = date >= state.statistics.startDate && date <= state.statistics.endDate;
        const checked = completedDates.has(date);
        const total = totalByDate.get(date) || 0;
        const label = total
          ? `${date}：${checked ? "已打卡" : "未打卡"}，共 ${total} 篇推荐`
          : `${date}：没有推荐文章`;
        cells.push(`
          <span class="heatmap-day ${checked ? "is-checked" : ""} ${inRange ? "" : "is-outside"}" title="${label}" aria-label="${label}">
            ${day}
          </span>
        `);
      }
      return `
        <section class="heatmap-month">
          <h4>${monthName(month)}</h4>
          <div class="heatmap-weekdays" aria-hidden="true"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
          <div class="heatmap-days">${cells.join("")}</div>
        </section>
      `;
    })
    .join("");
}

function renderStatistics() {
  syncStatisticsDateRange();
  els.statisticsLoading.hidden = !state.statistics.loading;
  const articles = state.statistics.articles;
  const isEmpty = !state.statistics.loading && articles.length === 0;
  els.statisticsEmpty.hidden = !isEmpty;
  els.statisticsContent.hidden = state.statistics.loading || isEmpty;
  if (state.statistics.loading || isEmpty) return;

  const completed = articles.filter(isArticleCompleted).length;
  const scored = articles.filter((article) => article.score > 0);
  const average = scored.length ? scored.reduce((sum, article) => sum + article.score, 0) / scored.length : 0;
  const dayCount = new Set(articles.map((article) => article.digestDate)).size;
  const rawRate = articles.length ? (completed / articles.length) * 100 : 0;
  const rate = rawRate > 0 && rawRate < 1 ? rawRate.toFixed(1) : Math.round(rawRate);
  els.statArticleCount.textContent = articles.length;
  els.statDayCount.textContent = `${dayCount} 个推荐日`;
  els.statAverageScore.textContent = scored.length ? average.toFixed(1) : "-";
  els.statVideoCount.textContent = completed;
  els.statCompletionRate.textContent = `${rate}%`;
  els.statPendingCount.textContent = `${articles.length - completed} 篇待精读`;
  renderSourceChart(articles);
  renderScoreChart(articles);
  renderDifficultyChart(articles);
  renderVideoHeatmap(articles);
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
          ${articleFooter(article)}
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
          ${articleFooter(article)}
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
          <div class="link-row">
            ${externalLink(topic.source_url, "查看热榜来源 →")}
            ${externalLink(topic.official_english_url, "查看英文报道 →")}
          </div>
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
  const version = ++state.loadVersion.articles;
  try {
    const response = await fetch(digest.file, { cache: "no-store" });
    if (!response.ok) throw new Error(`Failed to load ${digest.file}`);
    const rawMarkdown = await response.text();
    if (version !== state.loadVersion.articles) return false;
    state.selected = digest;
    state.rawMarkdown = rawMarkdown;
    state.articles = parseDigest(rawMarkdown, digest.date, "english").articles;
    renderView();
    return true;
  } catch (error) {
    if (version === state.loadVersion.articles) console.error(error);
    return false;
  }
}

async function loadJapaneseDigest(digest) {
  const version = ++state.loadVersion.japanese;
  try {
    const response = await fetch(digest.file, { cache: "no-store" });
    if (!response.ok) throw new Error(`Failed to load ${digest.file}`);
    const rawMarkdown = await response.text();
    if (version !== state.loadVersion.japanese) return false;
    state.selectedJapanese = digest;
    state.rawJapaneseMarkdown = rawMarkdown;
    state.japaneseArticles = parseDigest(rawMarkdown, digest.date, "japanese").articles;
    renderView();
    return true;
  } catch (error) {
    if (version === state.loadVersion.japanese) console.error(error);
    return false;
  }
}

async function loadHotTopicDigest(digest) {
  const version = ++state.loadVersion.topics;
  try {
    const response = await fetch(digest.file, { cache: "no-store" });
    if (!response.ok) throw new Error("Hot topics not found");
    const data = await response.json();
    if (version !== state.loadVersion.topics) return false;
    state.selectedHotTopics = digest;
    state.hotTopicsMeta = data;
    state.hotTopics = Array.isArray(data.topics) ? data.topics : [];
    renderView();
    return true;
  } catch (error) {
    if (version === state.loadVersion.topics) console.warn(error);
    return false;
  }
}

async function loadHotTopics() {
  try {
    const response = await fetch("data/hot_topics_index.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Hot topics index not found");
    const data = await response.json();
    state.hotTopicDigests = Array.isArray(data.digests) ? data.digests : [];
    if (state.hotTopicDigests.length > 0) {
      const loaded = await loadHotTopicDigest(state.hotTopicDigests[0]);
      if (loaded) return;
    }
  } catch (error) {
    console.warn(error);
  }

  try {
    const response = await fetch("data/chinese_hot_topics.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Hot topics not found");
    const data = await response.json();
    state.hotTopicsMeta = data;
    state.hotTopics = Array.isArray(data.topics) ? data.topics : [];
    state.hotTopicDigests = data.date
      ? [
          {
            date: data.date,
            file: "data/chinese_hot_topics.json",
            title: `Domestic Hot Topics - ${data.date}`,
            item_count: state.hotTopics.length,
            updated_at: data.updated_at,
          },
        ]
      : [];
    state.selectedHotTopics = state.hotTopicDigests[0] || null;
  } catch (error) {
    console.warn(error);
    state.hotTopicsMeta = null;
    state.hotTopics = [];
    state.hotTopicDigests = [];
    state.selectedHotTopics = null;
  }
  if (state.view === "topics") renderView();
}

async function loadIndex() {
  try {
    const response = await fetch("data/digests_index.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Digest index not found");
    const data = await response.json();
    state.digests = Array.isArray(data.digests) ? data.digests : [];
    syncStatisticsDateRange();
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
    syncStatisticsDateRange();
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
  const digests =
    state.view === "topics"
      ? state.hotTopicDigests
      : state.view === "japanese"
        ? state.japaneseDigests
        : state.digests;
  const digest = digests.find((item) => item.date === button.dataset.date);
  if (!digest) return;
  if (state.view === "topics") {
    loadHotTopicDigest(digest);
  } else if (state.view === "japanese") {
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
  const content =
    state.view === "topics"
      ? JSON.stringify(state.hotTopicsMeta, null, 2)
      : state.view === "japanese"
        ? state.rawJapaneseMarkdown
        : state.rawMarkdown;
  if (!content) return;
  try {
    await navigator.clipboard.writeText(content);
    els.copyMarkdown.textContent = "✓";
  } catch (error) {
    console.warn(error);
    els.copyMarkdown.textContent = "!";
  }
  window.setTimeout(() => {
    els.copyMarkdown.textContent = "⧉";
  }, 1200);
});

function handleCompletionClick(event) {
  const button = event.target.closest("[data-article-id]");
  if (!button) return;
  const candidates = [...state.articles, ...state.japaneseArticles, ...state.statistics.articles];
  const article = candidates.find((item) => item.id === button.dataset.articleId);
  if (article) toggleArticleCompleted(article);
}

els.grid.addEventListener("click", handleCompletionClick);
els.japaneseGrid.addEventListener("click", handleCompletionClick);

els.statisticsStartDate.addEventListener("change", (event) => {
  state.statistics.startDate = event.target.value;
  if (state.statistics.endDate < state.statistics.startDate) {
    state.statistics.endDate = state.statistics.startDate;
  }
  syncStatisticsDateRange();
  loadStatistics();
});

els.statisticsEndDate.addEventListener("change", (event) => {
  state.statistics.endDate = event.target.value;
  if (state.statistics.startDate > state.statistics.endDate) {
    state.statistics.startDate = state.statistics.endDate;
  }
  syncStatisticsDateRange();
  loadStatistics();
});

els.statisticsLanguage.addEventListener("change", (event) => {
  state.statistics.language = event.target.value;
  loadStatistics();
});

window.addEventListener("hashchange", () => {
  state.page = window.location.hash === "#statistics" ? "statistics" : "reader";
  renderView();
  if (state.page === "statistics") loadStatistics();
});

async function initializeApp() {
  els.runWorkflow.href = getWorkflowUrl();
  syncHistoryPanelForViewport();
  await Promise.all([loadHotTopics(), loadIndex(), loadJapaneseIndex()]);
  syncStatisticsDateRange();
  renderView();
  if (state.page === "statistics") await loadStatistics();
}

window.addEventListener("resize", syncHistoryPanelForViewport);
initializeApp();
