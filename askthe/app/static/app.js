// Ask pages: the catalog of creators (/), a creator's page (/<slug>: who they are,
// the ask box, starters, your questions) and one page per answer (/a/<id>).
// No framework and no build step. See docs/UI_PLAN.md.
"use strict";

const $ = (id) => document.getElementById(id);
const OLD_HISTORY_KEY = "askthe.history"; // before history was kept per creator
const HISTORY_MAX = 20;
const WATCH_LABEL = "▶ Watch on YouTube"; // a source with a `medium` is read, not watched
const creators = new Map(); // slug -> creator info, fetched once
let creator = null; // the creator on screen
let current = null; // the answer on screen

// --- Your questions (kept in this browser only, per creator) ------------------------

const historyKey = (slug) => `askthe.history.${slug}`;

function loadHistory(slug) {
  try {
    return JSON.parse(localStorage.getItem(historyKey(slug))) || [];
  } catch {
    return [];
  }
}

function saveHistory(slug, items) {
  try {
    localStorage.setItem(historyKey(slug), JSON.stringify(items));
  } catch {
    // Private browsing or storage off: the answer link still works.
  }
}

function keepRecent(items) {
  // Keep saved ones, then the most recent of the rest.
  const saved = items.filter((i) => i.saved);
  const recent = items.filter((i) => !i.saved).slice(0, Math.max(HISTORY_MAX - saved.length, 0));
  return items.filter((i) => saved.includes(i) || recent.includes(i));
}

function remember(answer) {
  const items = loadHistory(answer.creator).filter((i) => i.id !== answer.id);
  items.unshift({ id: answer.id, question: answer.question, askedAt: answer.asked_at, saved: false });
  saveHistory(answer.creator, keepRecent(items));
}

function isSaved(answer) {
  return loadHistory(answer.creator).some((i) => i.id === answer.id && i.saved);
}

function toggleSaved(answer) {
  const items = loadHistory(answer.creator);
  const item = items.find((i) => i.id === answer.id);
  if (item) item.saved = !item.saved;
  saveHistory(answer.creator, items);
  return Boolean(item && item.saved);
}

async function fetchUpdates(ids) {
  // For each answer: its creator, and how many new videos match it.
  const response = await fetch("/api/answers/updates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) throw new Error("updates");
  return response.json();
}

async function migrateHistory() {
  // History from before it was kept per creator: file each question under its
  // answer's creator. Answers the server doesn't serve are dropped.
  let old;
  try {
    old = JSON.parse(localStorage.getItem(OLD_HISTORY_KEY));
  } catch {
    return;
  }
  if (!Array.isArray(old)) return;
  try {
    const found = await fetchUpdates(old.map((i) => i.id).slice(0, 50));
    for (const item of old) {
      const slug = found[item.id] && found[item.id].creator;
      if (!slug) continue;
      const items = loadHistory(slug);
      if (!items.some((i) => i.id === item.id)) items.push(item);
      saveHistory(slug, keepRecent(items.sort((a, b) => b.askedAt.localeCompare(a.askedAt))));
    }
    localStorage.removeItem(OLD_HISTORY_KEY);
  } catch {
    // Try again next visit.
  }
}

// --- Creators ------------------------------------------------------------------------

async function getCreator(slug) {
  if (!creators.has(slug)) {
    const response = await fetch(`/api/creators/${encodeURIComponent(slug)}`);
    if (!response.ok) return null;
    creators.set(slug, await response.json());
  }
  return creators.get(slug);
}

function initials(name) {
  // "The Gear Shed" -> "GS": a leading article is skipped when more follows.
  let words = name.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w));
  if (words.length > 1 && /^(the|a|an)$/i.test(words[0])) words = words.slice(1);
  return words
    .slice(0, 2)
    .map((w) => w.match(/[\p{L}\p{N}]/u)[0].toUpperCase())
    .join("");
}

function avatar(c, size, id) {
  // The channel's own picture when there is one, else a monogram of the name.
  const img = c.avatar
    ? `<img src="${escapeHtml(c.avatar)}" alt="" referrerpolicy="no-referrer">`
    : "";
  return (
    `<span${id ? ` id="${id}"` : ""} class="avatar ${size}" aria-hidden="true">` +
    `${escapeHtml(initials(c.display_name))}${img}</span>`
  );
}

// A picture that fails to load leaves the monogram showing.
document.addEventListener(
  "error",
  (e) => e.target.tagName === "IMG" && e.target.closest(".avatar") && e.target.remove(),
  true,
);

// --- Rendering answers --------------------------------------------------------------

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function inline(text, verified) {
  // Bold, italics and [n] citation markers. Citations stay grey until verified.
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/\[(\d+)\]/g, (_, n) => {
      const ok = verified && verified.has(Number(n));
      return `<button class="cite${ok ? "" : " pending"}" data-n="${n}"${ok ? "" : " disabled"}>${n}</button>`;
    });
}

function markdown(text, verified) {
  // Paragraphs, bullet lists and headings: what answers use. Line by line, so a bold
  // label followed directly by its bullets renders as a label and a list.
  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => {
    if (para.length) out.push(`<p>${para.map((l) => inline(l, verified)).join("<br>")}</p>`);
    para = [];
  };
  const flushList = () => {
    if (list) out.push(`<ul>${list.join("")}</ul>`);
    list = null;
  };
  for (const raw of text.trim().split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (bullet) {
      flushPara();
      (list = list || []).push(`<li>${inline(bullet[1], verified)}</li>`);
    } else if (!line.trim()) {
      flushPara();
      flushList();
    } else if (/^#{1,4}\s/.test(line)) {
      flushPara();
      flushList();
      out.push(`<p><strong>${inline(line.replace(/^#+\s*/, ""), verified)}</strong></p>`);
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara();
  flushList();
  return out.join("");
}

function splitLead(text) {
  // The first paragraph is the direct answer: it goes in the verdict card.
  const parts = text.trim().split(/\n\s*\n/);
  return [parts[0] || "", parts.slice(1).join("\n\n")];
}

function formatDate(iso) {
  return new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function chipFor(answer) {
  // At most one chip.
  if (answer.coverage === "none") return "Not covered";
  if (answer.changed_mind) return `${possessive()} view changed`;
  if (answer.coverage === "partial") return "Partly covered";
  return null;
}

function possessive() {
  const p = (creator && creator.pronoun) || "they";
  return { he: "His", she: "Her", it: "Its" }[p.toLowerCase()] || "Their";
}

function showText(text, verified) {
  const [lead, rest] = splitLead(text);
  $("verdict").hidden = !lead;
  $("lead").innerHTML = markdown(lead, verified);
  $("body").innerHTML = markdown(rest, verified);
}

function showAnswer(answer) {
  const verified = new Set(answer.sources.map((s) => s.n));
  $("progress").hidden = true;
  $("reading").hidden = true;
  $("asked").textContent = answer.question;
  document.title = `${answer.question} · ${creator.name}`;
  setCreatorLinks();
  showText(answer.answer, verified);

  const chip = chipFor(answer);
  $("chip").hidden = !chip;
  $("chip").textContent = chip || "";
  $("verdict").classList.toggle("not-covered", answer.coverage === "none");

  showSources(answer.sources);
  showNewer(answer);
  $("answer-foot").hidden = false;
  $("save").hidden = false;
  $("share").hidden = false;
  setSaved(isSaved(answer));
  current = answer;
}

function showSources(sources) {
  const byVideo = new Map();
  for (const s of sources) {
    if (!byVideo.has(s.video_id)) byVideo.set(s.video_id, { ...s, quotes: [] });
    byVideo.get(s.video_id).quotes.push(s);
  }
  const groups = [...byVideo.values()].sort((a, b) => b.published.localeCompare(a.published));
  $("sources").hidden = groups.length === 0;
  // Written items (a LinkedIn post) are named by their medium, not called videos.
  const noun = groups.every((g) => !g.medium) ? "video" : "source";
  $("sources-label").textContent =
    groups.length === 1 ? `From 1 ${noun}` : `From ${groups.length} ${noun}s, newest first`;
  $("source-list").innerHTML = groups
    .map((g, i) => {
      const quotes = g.quotes
        .sort((a, b) => a.n - b.n)
        .map(
          (q) =>
            `<li><button class="cite" data-n="${q.n}">${q.n}</button> <q>${escapeHtml(q.quote)}</q>` +
            (q.sponsored ? '<span class="tag">Sponsored</span>' : "") +
            (q.in_description ? '<span class="tag">Description</span>' : "") +
            (q.medium && q === g.quotes[0] ? `<span class="tag">${escapeHtml(q.medium)}</span>` : "") +
            "</li>",
        )
        .join("");
      return (
        `<div class="video-group"><p class="video"><a href="${g.url}" target="_blank" rel="noopener">` +
        `${escapeHtml(g.title)}</a>${i === 0 && groups.length > 1 ? '<span class="tag newest">Newest</span>' : ""}` +
        `<span class="date">${formatDate(g.published)}</span></p><ul class="quotes">${quotes}</ul></div>`
      );
    })
    .join("");
}

function showNewer(answer) {
  const newer = answer.newer_videos || [];
  $("newer").hidden = newer.length === 0;
  if (!newer.length) return;
  const n = newer.length;
  $("newer").innerHTML =
    `<p><strong>${n} new video${n > 1 ? "s" : ""} since you asked</strong></p>` +
    `<button class="primary" id="ask-again">Ask again with the latest videos</button>`;
  $("ask-again").onclick = () => startAsk(answer.question);
}

// --- The source sheet --------------------------------------------------------------

function openBioSheet(ref) {
  // A quote behind a journey milestone or venture: his words and the video they're from.
  const [kind, i, k] = ref.split(".");
  const c = creator && creator[kind] && creator[kind][Number(i)];
  const cite = c && c.citations[Number(k)];
  if (!cite) return;
  $("sheet-kind").textContent = "Listen for";
  $("sheet-quote").textContent = cite.quote;
  $("sheet-context-block").hidden = true;
  $("sheet-tags").hidden = true;
  $("sheet-video").hidden = !cite.title;
  $("sheet-video").innerHTML = cite.title
    ? `${escapeHtml(cite.title)}<span class="date">${formatDate(cite.published)}</span>`
    : "";
  $("sheet-watch").href = cite.url;
  $("sheet-watch").textContent = cite.medium ? `Read the ${cite.medium}` : WATCH_LABEL;
  $("sheet").hidden = false;
}

function openSheet(n) {
  const s = current && current.sources.find((x) => x.n === n);
  if (!s) return;
  $("sheet-video").hidden = false;
  $("sheet-kind").textContent = s.in_description
    ? "From the video description"
    : s.medium
      ? `From a ${s.medium}`
      : "Listen for";
  $("sheet-quote").textContent = s.quote;
  // What he said around the quote, verbatim, with the quote highlighted.
  const hasContext = Boolean(s.context_before || s.context_after);
  $("sheet-context-block").hidden = !hasContext;
  $("sheet-context-label").textContent = s.in_description ? "In the description" : "In context";
  const after = s.context_after || "";
  const gap = /^[.,;:!?)]/.test(after) ? "" : " "; // no space before punctuation
  $("sheet-context").innerHTML = hasContext
    ? `${escapeHtml(s.context_before || "")} <mark>${escapeHtml(s.quote)}</mark>${gap}${escapeHtml(after)}`
    : "";
  $("sheet-tags").innerHTML = s.sponsored
    ? `<span class="tag">Sponsored: a paid read, not ${possessive().toLowerCase()} own verdict</span>`
    : "";
  $("sheet-tags").hidden = !s.sponsored;
  $("sheet-video").innerHTML = `${escapeHtml(s.title)}<span class="date">${formatDate(s.published)}</span>`;
  $("sheet-watch").href = s.url;
  $("sheet-watch").textContent = s.medium ? `Read the ${s.medium}` : WATCH_LABEL;
  $("sheet").hidden = false;
}

document.addEventListener("click", (e) => {
  const cite = e.target.closest(".cite");
  if (cite && cite.dataset.bio) openBioSheet(cite.dataset.bio);
  else if (cite && !cite.disabled) openSheet(Number(cite.dataset.n));
  if (e.target.closest("[data-close]")) $("sheet").hidden = true;
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("sheet").hidden = true;
});

// --- Asking ------------------------------------------------------------------------

function resetAnswerView(question) {
  current = null;
  $("asked").textContent = question;
  $("verdict").hidden = true;
  $("chip").hidden = true;
  $("lead").innerHTML = "";
  $("body").innerHTML = "";
  $("sources").hidden = true;
  $("newer").hidden = true;
  $("answer-foot").hidden = true;
  $("save").hidden = true;
  $("share").hidden = true;
  $("reading").hidden = true;
  setProgress(`Searching ${possessive().toLowerCase()} videos…`);
}

function setProgress(text) {
  $("progress").hidden = !text;
  $("progress").textContent = text || "";
}

async function startAsk(question) {
  showView("answer");
  const home = `/${creator.slug}`;
  if (location.pathname !== home) history.pushState({}, "", home);
  setCreatorLinks();
  resetAnswerView(question);
  let response;
  try {
    response = await fetch(`/api/creators/${creator.slug}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  } catch {
    return fail("Couldn't reach the server. Check your connection and try again.");
  }
  if (!response.ok) return fail("That question couldn't be asked. Try rephrasing it.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (line.trim()) handleEvent(JSON.parse(line));
    }
  }
}

function handleEvent(event) {
  switch (event.type) {
    case "reading": {
      const n = event.videos.length;
      setProgress(n ? `Reading ${n} video${n > 1 ? "s" : ""}…` : "Writing…");
      $("reading").innerHTML = event.videos.map((v) => `<li>${escapeHtml(v.title)}</li>`).join("");
      $("reading").hidden = n === 0;
      break;
    }
    case "writing":
      $("reading").hidden = true;
      setProgress("Writing, then checking every quote…");
      showText(event.text, null);
      break;
    case "retrying":
      setProgress("A quote didn't match, rewriting…");
      showText("", null);
      break;
    case "done":
      remember(event.answer);
      history.replaceState({}, "", `/a/${event.answer.id}`);
      showAnswer(event.answer);
      break;
    case "error":
      fail(event.message);
      break;
  }
}

function fail(message) {
  setProgress("");
  $("verdict").hidden = false;
  $("chip").hidden = true;
  $("lead").innerHTML = `<p>${escapeHtml(message)}</p>`;
  $("answer-foot").hidden = false;
}

// --- Actions on an answer ---------------------------------------------------------------

function setSaved(saved) {
  $("save").textContent = saved ? "★" : "☆";
  $("save").setAttribute("aria-pressed", String(saved));
  $("save").setAttribute("aria-label", saved ? "Saved" : "Save");
}

$("save").onclick = () => current && setSaved(toggleSaved(current));

$("share").onclick = async () => {
  if (!current) return;
  const url = `${location.origin}/a/${current.id}`;
  if (navigator.share) {
    try {
      await navigator.share({ title: current.question, url });
    } catch {
      // Cancelled.
    }
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    $("share").textContent = "✓";
    setTimeout(() => ($("share").textContent = "⤴"), 1500);
  } catch {
    prompt("Copy this link:", url);
  }
};

$("flag").onclick = async () => {
  if (!current) return;
  const note = prompt("What's wrong with this answer? (optional)");
  if (note === null) return;
  await fetch(`/api/answers/${current.id}/flag`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  $("flag").textContent = "Thanks, we'll take a look";
  $("flag").disabled = true;
};

// --- Catalog ------------------------------------------------------------------------

async function showCatalog() {
  showView("catalog");
  document.title = "Ask";
  let list = [];
  try {
    list = await (await fetch("/api/creators")).json();
  } catch {
    // An empty catalog; the page still renders.
  }
  $("creators").innerHTML = list
    .map(
      (c) =>
        `<li><a class="card" href="/${c.slug}">${avatar(c, "medium")}<span class="card-text">` +
        `<span class="card-name">${escapeHtml(c.name)}</span>` +
        (c.tagline ? `<span class="card-tagline">${escapeHtml(c.tagline)}</span>` : "") +
        `<span class="card-meta">${c.videos} video${c.videos === 1 ? "" : "s"}</span>` +
        `</span></a></li>`,
    )
    .join("");
}

// --- A creator's page -------------------------------------------------------------------

function setCreatorLinks() {
  $("back").href = `/${creator.slug}`;
  $("ask-else").href = `/${creator.slug}`;
}

function bioItems(kind, items) {
  // Journey milestones and ventures: when (if he said), what, and his own words on tap.
  return items
    .map((item, i) => {
      const cites = item.citations
        .map((_, k) => `<button class="cite" data-bio="${kind}.${i}.${k}">${k + 1}</button>`)
        .join("");
      return (
        "<li>" +
        (item.when ? `<span class="when">${escapeHtml(item.when)}</span>` : "") +
        `<strong>${escapeHtml(item.title)}</strong><span class="text">${escapeHtml(item.text)}${cites}</span>` +
        "</li>"
      );
    })
    .join("");
}

function showCreatorHeader() {
  // Who this is, in one line: the same on every tab.
  const c = creator;
  $("avatar").outerHTML = avatar(c, "large", "avatar");
  $("title").textContent = c.name;
  $("tagline").hidden = !c.tagline;
  $("tagline").textContent = c.tagline || "";
  for (const tab of ["ask", "about", "questions"]) {
    $(`tab-${tab}`).href = tab === "ask" ? `/${c.slug}` : `/${c.slug}/${tab}`;
  }
  $("tab-questions").hidden = loadHistory(c.slug).length === 0;
}

function showAskPanel() {
  const c = creator;
  const n = c.videos;
  $("scope").textContent =
    `Answered only from ${possessive().toLowerCase()} ${n} video${n === 1 ? "" : "s"}, quoted and dated.`;
  $("question").placeholder = `Ask about ${c.categories.slice(0, 3).join(", ")}…`;
  const starters = c.starters || [];
  $("starters").hidden = starters.length === 0;
  $("starters").querySelector("ul").innerHTML = starters
    .map((q) => `<li><button type="button">${escapeHtml(q)}</button></li>`)
    .join("");
  $("starters").querySelectorAll("button").forEach((b) => (b.onclick = () => startAsk(b.textContent)));
}

function showAboutPanel() {
  // Who he is beyond one video, every line backed by his own words.
  const c = creator;
  $("summary").hidden = !c.summary;
  $("summary").textContent = c.summary || "";
  $("links").innerHTML = c.links
    .map((l) => `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)}</a>`)
    .join("");
  let cited = false;
  for (const kind of ["journey", "ventures"]) {
    const items = c[kind] || [];
    $(kind).innerHTML = bioItems(kind, items);
    $(`${kind}-block`).hidden = items.length === 0;
    cited = cited || items.length > 0;
  }
  $("about-note").hidden = !cited;
  $("about-note").textContent =
    `Everything here is from ${possessive().toLowerCase()} own videos: tap a number to see the quote.`;
  $("about-ask").href = `/${c.slug}`;
  $("about-ask").textContent = c.name;
}

async function showQuestionsPanel() {
  const slug = creator.slug;
  const items = loadHistory(slug).sort((a, b) => (b.saved - a.saved) || b.askedAt.localeCompare(a.askedAt));
  const list = $("history");
  list.innerHTML = items.length
    ? items
        .map(
          (i) =>
            `<li><a href="/a/${i.id}">${i.saved ? "★ " : ""}${escapeHtml(i.question)}` +
            `<span class="meta" data-id="${i.id}">${formatDate(i.askedAt.slice(0, 10))}</span></a></li>`,
        )
        .join("")
    : `<li class="empty muted">Questions you ask ${escapeHtml(creator.name.replace(/^Ask /, ""))} appear here.</li>`;
  if (!items.length) return;
  try {
    const updates = await fetchUpdates(items.map((i) => i.id));
    for (const [id, { new: n }] of Object.entries(updates)) {
      if (!n) continue;
      const meta = list.querySelector(`.meta[data-id="${id}"]`);
      if (meta) meta.insertAdjacentHTML("beforeend", ` · <span class="new">${n} new video${n > 1 ? "s" : ""} since you asked</span>`);
    }
  } catch {
    // The list still works without the update badges.
  }
}

async function showHome(slug, tab = "ask") {
  const found = await getCreator(slug);
  if (!found) return showMissing();
  creator = found;
  showView("home");
  showCreatorHeader();
  for (const name of ["ask", "about", "questions"]) {
    $(`panel-${name}`).hidden = name !== tab;
    $(`tab-${name}`).classList.toggle("active", name === tab);
    if (name === tab) $(`tab-${name}`).setAttribute("aria-current", "page");
    else $(`tab-${name}`).removeAttribute("aria-current");
  }
  const titles = { ask: creator.name, about: `About · ${creator.name}`, questions: `Your questions · ${creator.name}` };
  document.title = titles[tab];
  if (tab === "about") showAboutPanel();
  else if (tab === "questions") await showQuestionsPanel();
  else showAskPanel();
}

function showMissing() {
  showView("missing");
  document.title = "Not found · Ask";
}

async function showStoredAnswer(id) {
  showView("answer");
  resetAnswerView("");
  setProgress("Loading…");
  const response = await fetch(`/api/answers/${id}`);
  const answer = response.ok ? await response.json() : null;
  creator = answer && (await getCreator(answer.creator));
  if (!answer || !creator) {
    $("back").href = "/";
    $("ask-else").href = "/";
    return fail("That answer can't be found.");
  }
  showAnswer(answer);
}

function showView(name) {
  for (const view of ["catalog", "home", "missing"]) $(view).hidden = name !== view;
  $("answer").hidden = name !== "answer";
  document.body.dataset.view = name;
  $("sheet").hidden = true;
  window.scrollTo(0, 0);
}

function route() {
  const path = location.pathname.replace(/\/+$/, "");
  const answer = path.match(/^\/a\/([\w-]+)$/);
  const slug = path.match(/^\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\/(about|questions))?$/);
  if (answer) showStoredAnswer(answer[1]);
  else if (slug) showHome(slug[1], slug[2] || "ask");
  else if (!path) showCatalog();
  else showMissing();
}

$("ask-form").onsubmit = (e) => {
  e.preventDefault();
  const question = $("question").value.trim();
  if (question.length >= 3) startAsk(question);
};

$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("ask-form").requestSubmit();
  }
});

document.addEventListener("click", (e) => {
  // Internal links route in place.
  const a = e.target.closest("a[href^='/']");
  if (!a || a.target) return;
  e.preventDefault();
  history.pushState({}, "", a.getAttribute("href"));
  route();
});

window.addEventListener("popstate", route);

(async function init() {
  await migrateHistory();
  route();
})();
