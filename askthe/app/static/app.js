// Ask page: home (ask box, starters, your questions) and one page per answer.
// No framework and no build step. See docs/UI_PLAN.md.
"use strict";

const $ = (id) => document.getElementById(id);
const HISTORY_KEY = "askthe.history";
const HISTORY_MAX = 20;
let creator = null;
let current = null; // the answer on screen

// --- Your questions (kept in this browser only) ---------------------------------

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
  } catch {
    return [];
  }
}

function saveHistory(items) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items));
  } catch {
    // Private browsing or storage off: the answer link still works.
  }
}

function remember(answer) {
  const items = loadHistory().filter((i) => i.id !== answer.id);
  items.unshift({ id: answer.id, question: answer.question, askedAt: answer.asked_at, saved: false });
  // Keep saved ones, then the most recent of the rest.
  const saved = items.filter((i) => i.saved);
  const recent = items.filter((i) => !i.saved).slice(0, Math.max(HISTORY_MAX - saved.length, 0));
  saveHistory(items.filter((i) => saved.includes(i) || recent.includes(i)));
}

function isSaved(id) {
  return loadHistory().some((i) => i.id === id && i.saved);
}

function toggleSaved(id) {
  const items = loadHistory();
  const item = items.find((i) => i.id === id);
  if (item) item.saved = !item.saved;
  saveHistory(items);
  return Boolean(item && item.saved);
}

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
  return { he: "His", she: "Her" }[p.toLowerCase()] || "Their";
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
  setSaved(isSaved(answer.id));
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
  $("sources-label").textContent =
    groups.length === 1 ? "From 1 video" : `From ${groups.length} videos, newest first`;
  $("source-list").innerHTML = groups
    .map((g, i) => {
      const quotes = g.quotes
        .sort((a, b) => a.n - b.n)
        .map(
          (q) =>
            `<li><button class="cite" data-n="${q.n}">${q.n}</button> <q>${escapeHtml(q.quote)}</q>` +
            (q.sponsored ? '<span class="tag">Sponsored</span>' : "") +
            (q.in_description ? '<span class="tag">Description</span>' : "") +
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

function openSheet(n) {
  const s = current && current.sources.find((x) => x.n === n);
  if (!s) return;
  $("sheet-kind").textContent = s.in_description ? "From the video description" : "Listen for";
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
    ? '<span class="tag">Sponsored: a paid read, not his own verdict</span>'
    : "";
  $("sheet-tags").hidden = !s.sponsored;
  $("sheet-video").innerHTML = `${escapeHtml(s.title)}<span class="date">${formatDate(s.published)}</span>`;
  $("sheet-watch").href = s.url;
  $("sheet").hidden = false;
}

document.addEventListener("click", (e) => {
  const cite = e.target.closest(".cite");
  if (cite && !cite.disabled) openSheet(Number(cite.dataset.n));
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
  if (location.pathname !== "/") history.pushState({}, "", "/");
  resetAnswerView(question);
  let response;
  try {
    response = await fetch("/api/ask", {
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

$("save").onclick = () => current && setSaved(toggleSaved(current.id));

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

// --- Home --------------------------------------------------------------------------

async function showHome() {
  showView("home");
  document.title = creator.name;
  const items = loadHistory().sort((a, b) => (b.saved - a.saved) || b.askedAt.localeCompare(a.askedAt));
  $("history").hidden = items.length === 0;
  const list = $("history").querySelector("ul");
  list.innerHTML = items
    .map(
      (i) =>
        `<li><a href="/a/${i.id}">${i.saved ? "★ " : ""}${escapeHtml(i.question)}` +
        `<span class="meta" data-id="${i.id}">${formatDate(i.askedAt.slice(0, 10))}</span></a></li>`,
    )
    .join("");
  if (!items.length) return;
  try {
    const response = await fetch("/api/answers/updates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: items.map((i) => i.id) }),
    });
    const counts = await response.json();
    for (const [id, n] of Object.entries(counts)) {
      if (!n) continue;
      const meta = list.querySelector(`.meta[data-id="${id}"]`);
      if (meta) meta.insertAdjacentHTML("beforeend", ` · <span class="new">${n} new video${n > 1 ? "s" : ""} since you asked</span>`);
    }
  } catch {
    // The list still works without the update badges.
  }
}

async function showStoredAnswer(id) {
  showView("answer");
  resetAnswerView("");
  setProgress("Loading…");
  const response = await fetch(`/api/answers/${id}`);
  if (!response.ok) return fail("That answer can't be found.");
  showAnswer(await response.json());
}

function showView(name) {
  $("home").hidden = name !== "home";
  $("answer").hidden = name !== "answer";
  $("sheet").hidden = true;
  window.scrollTo(0, 0);
}

function route() {
  const match = location.pathname.match(/^\/a\/([\w-]+)$/);
  if (match) showStoredAnswer(match[1]);
  else showHome();
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
  creator = await (await fetch("/api/creator")).json();
  $("title").textContent = creator.name;
  $("subtitle").textContent =
    `Answers only from ${creator.refer_to}'s ${creator.videos} videos, quoted and dated.`;
  $("question").placeholder = `Ask about ${creator.categories.slice(0, 3).join(", ")}…`;
  const starters = creator.starters || [];
  $("starters").hidden = starters.length === 0;
  $("starters").querySelector("ul").innerHTML = starters
    .map((q) => `<li><button type="button">${escapeHtml(q)}</button></li>`)
    .join("");
  $("starters").querySelectorAll("button").forEach((b) => (b.onclick = () => startAsk(b.textContent)));
  route();
})();
