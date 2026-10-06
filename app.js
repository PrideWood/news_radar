const sources = {
  articles: "data/digests_index.json",
  japanese: "data/japanese_digests_index.json",
  topics: "data/hot_topics_index.json",
};
const view = document.querySelector("#section-select");
const dates = document.querySelector("#date-select");
const search = document.querySelector("#digest-search");
const list = document.querySelector("#article-list");
const status = document.querySelector("#status");
let entries = [];
let items = [];
let version = 0;

function safeHref(value) {
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function parseDigest(markdown) {
  return markdown.split(/^##\s+/m).slice(1).map(section => {
    const lines = section.trim().split("\n");
    const title = lines.shift().replace(/^\d+\.\s*/, "");
    const fields = {};
    for (const line of lines) {
      const match = line.match(/^-\s+\*\*(.+?):\*\*\s*(.*)$/);
      if (match) fields[match[1]] = match[2];
    }
    return { title, outlet: fields.Outlet, date: fields["Publication date"], link: fields.Link, summary: fields.Summary || "" };
  });
}

async function fetchFile(path, json = true) {
  const href = safeHref(path);
  if (!href || new URL(href).origin !== window.location.origin) throw new Error("无效的数据路径");
  const response = await fetch(href, { cache: "no-cache" });
  if (!response.ok) throw new Error("数据暂时无法加载");
  return json ? response.json() : response.text();
}

function render() {
  const query = search.value.trim().toLowerCase();
  const filtered = items.filter(item => [item.title, item.outlet, item.summary].join(" ").toLowerCase().includes(query));
  list.replaceChildren();
  for (const item of filtered) {
    const article = document.createElement("article");
    const heading = document.createElement("h2");
    const href = item.link && safeHref(item.link);
    if (href) {
      const link = document.createElement("a");
      link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = item.title;
      heading.append(link);
    } else heading.textContent = item.title;
    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = [item.outlet, item.date === "Not listed" ? "" : item.date].filter(Boolean).join(" · ");
    const summary = document.createElement("p");
    summary.textContent = item.summary || (view.value === "topics" ? "来源未提供摘要。" : "暂无来源摘要，可打开链接阅读原文。");
    article.append(heading, meta, summary);
    if (href) {
      const link = document.createElement("a");
      link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "查看原文 ↗"; link.className = "original-link";
      article.append(link);
    }
    list.append(article);
  }
  status.textContent = items.length ? `${filtered.length} 条${query ? `（共 ${items.length} 条）` : ""}` : "这个日期暂无条目。";
}

async function loadItems() {
  const current = ++version;
  items = []; list.replaceChildren(); status.textContent = "正在加载…";
  const entry = entries.find(entry => entry.date === dates.value);
  if (!entry) { render(); return; }
  const selectedView = view.value;
  try {
    const data = await fetchFile(entry.file, selectedView === "topics");
    if (current !== version) return;
    items = selectedView === "topics"
      ? (data.topics || []).map(topic => ({ title: topic.chinese_topic, outlet: topic.platform, date: data.date, link: topic.source_url, summary: topic.summary || (topic.heat ? `热度：${topic.heat}` : "") }))
      : parseDigest(data);
    render();
  } catch (error) { if (current === version) status.textContent = `${error.message}，请稍后刷新重试。`; }
}

async function loadView() {
  const current = ++version;
  const previousDate = dates.value;
  dates.replaceChildren(); list.replaceChildren(); items = []; entries = []; status.textContent = "正在加载…";
  try {
    const data = await fetchFile(sources[view.value]);
    if (current !== version) return;
    entries = (data.digests || []).sort((a, b) => b.date.localeCompare(a.date));
    for (const entry of entries) {
      const option = document.createElement("option");
      option.value = entry.date; option.textContent = entry.date; dates.append(option);
    }
    if (entries.some(entry => entry.date === previousDate)) dates.value = previousDate;
    dates.disabled = !entries.length;
    await loadItems();
  } catch (error) { if (current === version) status.textContent = `${error.message}，请稍后刷新重试。`; }
}
view.addEventListener("change", loadView);
dates.addEventListener("change", loadItems);
search.addEventListener("input", render);
loadView();
