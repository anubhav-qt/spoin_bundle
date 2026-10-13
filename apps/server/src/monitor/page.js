// The run monitor's page (task 0045). It polls the run, draws a box per chat in the pipeline's
// order with the helpers each one started under it, and polls one chat's detail while it is open.
// Everything from the database goes into the page as text, never as HTML: it is what models wrote.

const POLL_MS = 2500;
/** The server sends a transcript or record list in pages of this many. */
const PAGE = 300;
/** Text longer than this is folded, with its start showing. */
const FOLD_CHARS = 1500;

const PIPELINE = [
  { role: "toad_sage", does: "takes topics in, briefs helpers" },
  { role: "tadpole", does: "researches, writes documents, maps and cards" },
  { role: "curriculum", does: "turns documents into a curriculum" },
  { role: "designer_toad", does: "draws each accepted card's art" },
];

const TABS = ["transcript", "runs", "wakes", "model calls", "records"];

let state = null;
/** The server's clock minus this browser's, so "ago" is measured against the database's time. */
let skewMs = 0;

const open = {
  id: null,
  tab: "transcript",
  afterMessage: 0,
  afterRecord: 0,
  lastRunId: null,
  runs: new Map(),
  shown: { runs: "", wakes: "", calls: "" },
};

// ------------------------------------------------------------------ helpers --

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (name.startsWith("on")) {
      node.addEventListener(name.slice(2), value);
    } else if (value === true) {
      node.setAttribute(name, "");
    } else {
      node.setAttribute(name, String(value));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    if (child instanceof Node) {
      node.append(child);
    } else {
      node.append(String(child));
    }
  }
  return node;
}

/** Milliseconds from a time as Postgres writes it ("2026-10-13 07:17:46.3+00"), or a pi timestamp. */
function msOf(time) {
  if (typeof time === "number") return time;
  let iso = String(time).replace(" ", "T");
  if (/[+-]\d\d$/.test(iso)) iso = `${iso}:00`;
  return Date.parse(iso);
}

function serverNow() {
  return Date.now() + skewMs;
}

function span(ms) {
  const seconds = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(rest).padStart(2, "0")}s`;
  if (minutes > 0) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${rest}s`;
}

function ago(time) {
  if (!time) return "";
  return `${span(serverNow() - msOf(time))} ago`;
}

function clock(time) {
  if (!time) return "";
  return new Date(msOf(time)).toLocaleTimeString();
}

function tokens(count) {
  const n = Number(count);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

/** "1 run", "3 runs". */
function counted(count, word) {
  if (Number(count) === 1) return `1 ${word}`;
  return `${count} ${word}s`;
}

function shortId(id) {
  return String(id).slice(0, 8);
}

function nameOf(chat) {
  if (chat.role === "helper") return chat.task;
  return chat.role;
}

/** What a chat is doing: its running run, a wake on its way, or how its last run ended. */
function statusOf(chat) {
  if (chat.runStatus === "running") return "running";
  if (chat.taken > 0) return "starting";
  if (chat.waiting > 0) return "waiting";
  if (!chat.runStatus) return "new";
  return chat.runStatus;
}

function statusText(chat) {
  const status = statusOf(chat);
  if (status === "running") return `running for ${span(serverNow() - msOf(chat.runStartedAt))}`;
  if (status === "starting") return "starting a run";
  if (status === "waiting") {
    const due = msOf(chat.nextDueAt) - serverNow();
    if (due > 0) return `woken in ${span(due)}`;
    return "woken, waiting its turn";
  }
  if (status === "new") return "not run yet";
  if (status === "done") {
    if (chat.role === "helper") return `finished ${ago(chat.runEndedAt)}`;
    return `idle, last ran ${ago(chat.runEndedAt)}`;
  }
  if (status === "paused") return "paused to compact";
  return `${status} ${ago(chat.runEndedAt)}`;
}

function isBusy(chat) {
  const status = statusOf(chat);
  return status === "running" || status === "starting" || status === "waiting";
}

function triggerText(trigger) {
  if (trigger.kind === "schedule") return `schedule ${trigger.schedule}`;
  if (trigger.kind === "record")
    return `${trigger.record.kind} ${shortId(trigger.record.id)} v${trigger.record.version}`;
  if (trigger.kind === "job") return `topic job ${shortId(trigger.job)}`;
  if (trigger.kind === "compaction") return `compaction at ${tokens(trigger.contextTokens)} tokens`;
  if (trigger.kind === "continuation") return `carrying on run ${shortId(trigger.run)}`;
  return trigger.kind;
}

function triggersText(triggers) {
  if (!Array.isArray(triggers)) return triggerText(triggers);
  return triggers.map(triggerText).join(", ");
}

/** Text as it is, folded when long, so a document or a prompt doesn't push the rest away. */
function textBlock(text, label) {
  if (text.length <= FOLD_CHARS) {
    if (label) return h("div", { class: "fold" }, h("span", { class: "muted" }, label), h("pre", {}, text));
    return h("pre", {}, text);
  }
  const start = text.slice(0, 160).replace(/\s+/g, " ");
  const summary = label ? `${label} (${text.length} chars)` : `${start}… (${text.length} chars)`;
  return h("details", { class: "fold" }, h("summary", {}, summary), h("pre", {}, text));
}

function fold(summary, text, isOpen) {
  return h("details", { class: "fold", open: isOpen }, h("summary", {}, summary), h("pre", {}, text));
}

// ------------------------------------------------------------------- header --

function renderHeader() {
  const chats = state.chats;
  const helpers = chats.filter((chat) => chat.role === "helper").length;
  const running = chats.filter((chat) => statusOf(chat) === "running").length;
  const queued = chats.filter((chat) => statusOf(chat) === "waiting" || statusOf(chat) === "starting").length;
  let calls = 0;
  let failed = 0;
  let promptTokens = 0;
  let outputTokens = 0;
  for (const chat of chats) {
    calls += Number(chat.modelCalls);
    failed += Number(chat.failedCalls);
    promptTokens += Number(chat.promptTokens);
    outputTokens += Number(chat.outputTokens);
  }
  document
    .getElementById("totals")
    .replaceChildren(
      h("b", {}, counted(chats.length - helpers, "chat")),
      ", ",
      h("b", {}, counted(helpers, "helper")),
      " · ",
      h("b", {}, running),
      " running · ",
      h("b", {}, queued),
      " woken · ",
      h("b", {}, counted(calls, "model call")),
      ", ",
      h("b", {}, failed),
      " failed · tokens in ",
      h("b", {}, tokens(promptTokens)),
      ", out ",
      h("b", {}, tokens(outputTokens)),
    );

  const topics = state.topics.map((topic) =>
    h(
      "p",
      { class: "line" },
      h("b", {}, topic.name),
      `: ${counted(topic.subtopics, "subtopic")} · cards ${countsText(topic.cards)} · ${topic.withArt} with art · questions ${countsText(topic.questions)}`,
    ),
  );
  document.getElementById("topics").replaceChildren(...topics);

  const records = state.records.map((record) => `${record.kind} ${record.count}`);
  let recordsText = "";
  if (records.length > 0) recordsText = `records: ${records.join(" · ")}`;
  document.getElementById("records").textContent = recordsText;
  renderClock();
}

function countsText(counts) {
  const entries = Object.entries(counts ?? {});
  if (entries.length === 0) return "none yet";
  return entries.map(([stage, count]) => `${stage} ${count}`).join(", ");
}

/** The run's time: since its first run while anything is still going, first run to last end once idle. */
function renderClock() {
  const elapsed = document.getElementById("elapsed");
  const phase = document.getElementById("phase");
  if (!state) return;
  if (!state.clock.firstStartedAt) {
    elapsed.textContent = "no run yet";
    phase.textContent = "waiting for a topic";
    return;
  }
  const started = msOf(state.clock.firstStartedAt);
  if (state.chats.some(isBusy)) {
    elapsed.textContent = span(serverNow() - started);
    phase.textContent = `running since ${clock(state.clock.firstStartedAt)}`;
    return;
  }
  elapsed.textContent = span(msOf(state.clock.lastEndedAt) - started);
  phase.textContent = `idle: nothing running or woken since ${clock(state.clock.lastEndedAt)}`;
}

// ------------------------------------------------------------------ diagram --

function renderDiagram() {
  const steps = [...PIPELINE];
  for (const chat of state.chats) {
    const known = steps.some((step) => step.role === chat.role);
    if (chat.role !== "helper" && !known) steps.push({ role: chat.role, does: "" });
  }
  const parts = [];
  steps.forEach((step, index) => {
    if (index > 0) parts.push(h("div", { class: "arrow", "aria-hidden": "true" }, "→"));
    parts.push(column(step));
  });
  document.getElementById("diagram").replaceChildren(...parts);
}

function column(step) {
  const chats = state.chats.filter((chat) => chat.role === step.role);
  const body = [];
  if (chats.length === 0) {
    body.push(
      h(
        "div",
        { class: "box new" },
        h("span", { class: "name" }, step.role),
        h("span", { class: "state" }, "not started"),
      ),
    );
  }
  for (const chat of chats) {
    body.push(chatBox(chat));
    const helpers = state.chats.filter((one) => one.parentId === chat.id);
    if (helpers.length > 0) {
      body.push(
        h(
          "div",
          { class: "helpers" },
          h("p", { class: "helpers-label" }, counted(helpers.length, "helper")),
          helpers.map(helperBox),
        ),
      );
    }
  }
  return h(
    "section",
    { class: "column" },
    h("h2", {}, step.role),
    h("p", { class: "does" }, step.does),
    body,
  );
}

function chatBox(chat) {
  const lines = [h("span", { class: "name" }, nameOf(chat))];
  if (chat.topic) lines.push(h("span", { class: "topic" }, chat.topic));
  lines.push(h("span", { class: "state" }, h("span", { class: "dot" }), statusText(chat)));
  if (chat.lastTool)
    lines.push(h("span", { class: "meta" }, `last tool: ${chat.lastTool}, ${ago(chat.lastToolAt)}`));
  lines.push(
    h(
      "span",
      { class: "meta" },
      `${counted(chat.runs, "run")} · ${counted(chat.toolCalls, "tool call")} · ${counted(chat.messages, "message")}`,
    ),
  );
  lines.push(
    h(
      "span",
      { class: "meta" },
      `${counted(chat.modelCalls, "model call")} (${chat.failedCalls} failed) · in ${tokens(chat.promptTokens)}, out ${tokens(chat.outputTokens)}`,
    ),
  );
  lines.push(problemLine(chat));
  return h(
    "button",
    {
      class: `box ${statusOf(chat)}`,
      "aria-pressed": String(open.id === chat.id),
      onclick: () => openChat(chat.id),
    },
    lines,
  );
}

function helperBox(chat) {
  const lines = [
    h("span", { class: "name" }, nameOf(chat)),
    h("span", { class: "state" }, h("span", { class: "dot" }), statusText(chat)),
  ];
  if (chat.lastTool) lines.push(h("span", { class: "meta" }, `${chat.lastTool}, ${ago(chat.lastToolAt)}`));
  lines.push(
    h(
      "span",
      { class: "meta" },
      `${counted(chat.toolCalls, "tool call")} · ${counted(chat.modelCalls, "model call")}`,
    ),
  );
  lines.push(problemLine(chat));
  return h(
    "button",
    {
      class: `box small ${statusOf(chat)}`,
      "aria-pressed": String(open.id === chat.id),
      onclick: () => openChat(chat.id),
    },
    lines,
  );
}

/** A failed run, or a model call that failed last: what a stuck chat is stuck on. */
function problemLine(chat) {
  if (chat.runStatus === "failed") return h("span", { class: "warn" }, String(chat.runError).slice(0, 160));
  if (chat.lastCallOk === false)
    return h("span", { class: "warn" }, `last model call: ${chat.lastCallFailure}`);
  return null;
}

// ------------------------------------------------------------------- detail --

function openChat(id) {
  open.id = id;
  open.afterMessage = 0;
  open.afterRecord = 0;
  open.lastRunId = null;
  open.runs = new Map();
  open.shown = { runs: "", wakes: "", calls: "" };
  if (location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);

  const sections = TABS.map((tab) =>
    h("section", { id: `tab-${tab.replace(" ", "-")}`, hidden: tab !== open.tab }),
  );
  document.getElementById("detail-body").replaceChildren(...sections);
  document.getElementById("detail").hidden = false;
  renderDetailHead();
  if (state) renderDiagram();
  void pollChat(true);
}

function closeChat() {
  open.id = null;
  document.getElementById("detail").hidden = true;
  history.replaceState(null, "", location.pathname);
  if (state) renderDiagram();
}

function section(tab) {
  return document.getElementById(`tab-${tab.replace(" ", "-")}`);
}

function showTab(tab) {
  open.tab = tab;
  for (const one of TABS) section(one).hidden = one !== tab;
  renderDetailHead();
}

function renderDetailHead() {
  const head = document.getElementById("detail-head");
  let chat = null;
  if (state) chat = state.chats.find((one) => one.id === open.id) ?? null;
  const parts = [h("button", { class: "close", onclick: closeChat }, "close")];
  if (!chat) {
    parts.push(h("h2", {}, "Loading"));
    head.replaceChildren(...parts);
    return;
  }
  parts.push(h("h2", {}, nameOf(chat)));
  const facts = [statusText(chat)];
  if (chat.topic) facts.push(chat.topic);
  if (chat.model) facts.push(chat.model);
  facts.push(`chat ${shortId(chat.id)}`);
  parts.push(h("p", { class: "line" }, facts.join(" · ")));

  const links = [];
  if (chat.parentId) {
    const parent = state.chats.find((one) => one.id === chat.parentId);
    if (parent)
      links.push(
        h("button", { class: "chip", onclick: () => openChat(parent.id) }, `started by ${nameOf(parent)}`),
      );
  }
  for (const helper of state.chats.filter((one) => one.parentId === chat.id)) {
    links.push(
      h(
        "button",
        { class: "chip", onclick: () => openChat(helper.id) },
        `${helper.task}: ${statusText(helper)}`,
      ),
    );
  }
  if (links.length > 0) parts.push(h("div", { class: "chips" }, links));

  const tabs = TABS.map((tab) =>
    h(
      "button",
      { class: "tab", role: "tab", "aria-selected": String(tab === open.tab), onclick: () => showTab(tab) },
      tab,
    ),
  );
  parts.push(h("div", { class: "tabs", role: "tablist" }, tabs));
  head.replaceChildren(...parts);
}

async function pollChat(first) {
  const id = open.id;
  if (!id) return;
  const query = `afterMessage=${open.afterMessage}&afterRecord=${open.afterRecord}`;
  const response = await fetch(`/api/chats/${id}?${query}`);
  if (open.id !== id) return;
  if (!response.ok) {
    section("transcript").replaceChildren(
      h("p", { class: "warn" }, `This chat couldn't be read (${response.status}).`),
    );
    return;
  }
  const detail = await response.json();
  if (open.id !== id) return;

  for (const run of detail.runs) open.runs.set(run.id, run);
  const body = document.getElementById("detail-body");
  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 120;
  appendMessages(detail.messages);
  appendRecords(detail.records);
  replaceIfChanged("runs", detail.runs, renderRuns);
  replaceIfChanged("wakes", detail.wakes, renderWakes);
  replaceIfChanged("calls", detail.calls, renderCalls);
  renderDetailHead();
  if (detail.messages.length > 0 && open.tab === "transcript") {
    if (first || nearBottom) body.scrollTop = body.scrollHeight;
  }
  if (detail.messages.length === PAGE || detail.records.length === PAGE) await pollChat(first);
}

function replaceIfChanged(key, rows, render) {
  const shown = JSON.stringify(rows);
  if (open.shown[key] === shown) return;
  open.shown[key] = shown;
  render(rows);
}

function appendMessages(rows) {
  const transcript = section("transcript");
  if (open.afterMessage === 0 && rows.length === 0) {
    transcript.replaceChildren(h("p", { class: "muted" }, "Nothing in the transcript yet."));
    return;
  }
  if (open.afterMessage === 0) transcript.replaceChildren();
  for (const row of rows) {
    // Two polls can overlap when a chat is opened; a message already shown is skipped.
    if (row.seq <= open.afterMessage) continue;
    open.afterMessage = row.seq;
    if (row.runId !== open.lastRunId) {
      open.lastRunId = row.runId;
      transcript.append(runDivider(row.runId));
    }
    transcript.append(messageView(row.message));
  }
}

function runDivider(runId) {
  const run = open.runs.get(runId);
  if (!run) return h("div", { class: "run-divider" }, `run ${shortId(runId)}`);
  return h(
    "div",
    { class: "run-divider" },
    `run ${shortId(run.id)} · ${clock(run.startedAt)} · ${run.model} · woken by ${triggersText(run.triggers)}`,
  );
}

function messageView(message) {
  if (message.role === "user") {
    return h("div", { class: "msg user" }, who("woken with", message), userContent(message.content));
  }
  if (message.role === "assistant") return assistantView(message);
  if (message.role === "toolResult") return toolResultView(message);
  return h("div", { class: "msg" }, who(message.role, message), textBlock(JSON.stringify(message, null, 2)));
}

function who(label, message) {
  const facts = [];
  if (message.timestamp) facts.push(clock(message.timestamp));
  if (message.durationMs) facts.push(span(message.durationMs));
  if (message.usage) facts.push(`in ${tokens(message.usage.input)}, out ${tokens(message.usage.output)}`);
  return h("div", { class: "who" }, h("b", {}, label), facts.length > 0 ? ` · ${facts.join(" · ")}` : "");
}

function userContent(content) {
  if (typeof content === "string") return textBlock(content);
  return content.map((part) => {
    if (part.type === "text") return textBlock(part.text);
    if (part.type === "image") return h("img", { src: `data:${part.mimeType};base64,${part.data}`, alt: "" });
    return null;
  });
}

function assistantView(message) {
  const parts = [];
  for (const part of message.content) {
    if (part.type === "thinking")
      parts.push(fold(`thinking (${part.thinking.length} chars)`, part.thinking, false));
    if (part.type === "text" && part.text.trim() !== "") parts.push(textBlock(part.text));
    if (part.type === "toolCall") {
      const args = JSON.stringify(part.arguments, null, 2);
      parts.push(
        h(
          "details",
          { class: "fold", open: args.length < 600 },
          h("summary", {}, "calls ", h("span", { class: "call-name" }, part.name)),
          h("pre", {}, args),
        ),
      );
    }
  }
  if (message.errorMessage) parts.push(h("p", { class: "warn" }, message.errorMessage));
  return h("div", { class: "msg assistant" }, who(message.model, message), parts);
}

function toolResultView(message) {
  const text = message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n");
  const images = message.content
    .filter((part) => part.type === "image")
    .map((part) =>
      h("img", {
        src: `data:${part.mimeType};base64,${part.data}`,
        alt: `what ${message.toolName} returned`,
      }),
    );
  let label = `${message.toolName} returned`;
  if (message.isError) label = `${message.toolName} failed`;
  let className = "msg tool";
  if (message.isError) className = "msg tool error";
  return h("div", { class: className }, who(label, message), textBlock(text), images);
}

function appendRecords(rows) {
  const records = section("records");
  if (open.afterRecord === 0 && rows.length === 0) {
    records.replaceChildren(h("p", { class: "muted" }, "This chat hasn't written a record yet."));
    return;
  }
  if (open.afterRecord === 0) records.replaceChildren();
  for (const row of rows) {
    if (row.seq <= open.afterRecord) continue;
    open.afterRecord = row.seq;
    const head = `${row.kind} ${shortId(row.id)} v${row.version} · ${row.status} · ${clock(row.writtenAt)}`;
    records.prepend(
      h(
        "div",
        { class: "record" },
        h("b", {}, head),
        row.reason ? h("p", { class: "line" }, row.reason) : null,
        fold("body", JSON.stringify(row.body, null, 2), false),
      ),
    );
  }
}

function table(headings, rows) {
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          headings.map((heading) => h("th", {}, heading)),
        ),
      ),
      h("tbody", {}, rows),
    ),
  );
}

function renderRuns(runs) {
  if (runs.length === 0) {
    section("runs").replaceChildren(h("p", { class: "muted" }, "No run yet."));
    return;
  }
  const rows = [...runs].reverse().map((run) => {
    let ended = serverNow();
    if (run.endedAt) ended = msOf(run.endedAt);
    const prompt = h("div", {});
    const show = h(
      "button",
      {
        class: "small-button",
        onclick: async () => {
          const response = await fetch(`/api/runs/${run.id}/prompt`);
          prompt.replaceChildren(h("pre", { class: "prompt" }, await response.text()));
        },
      },
      "instructions",
    );
    return h(
      "tr",
      {},
      h("td", {}, clock(run.startedAt)),
      h("td", {}, run.status, run.error ? h("div", { class: "warn" }, run.error) : null),
      h("td", {}, span(ended - msOf(run.startedAt))),
      h("td", { class: "mono" }, run.model),
      h("td", {}, triggersText(run.triggers)),
      h("td", {}, `${run.calls} (${run.failed} failed)`),
      h("td", {}, `${tokens(run.promptTokens)} / ${tokens(run.outputTokens)}`),
      h("td", {}, show, prompt),
    );
  });
  section("runs").replaceChildren(
    table(["started", "status", "took", "model", "woken by", "model calls", "tokens in / out", ""], rows),
  );
}

function renderWakes(wakes) {
  if (wakes.length === 0) {
    section("wakes").replaceChildren(h("p", { class: "muted" }, "Never woken."));
    return;
  }
  const rows = wakes.map((wake) =>
    h(
      "tr",
      {},
      h("td", {}, clock(wake.createdAt)),
      h("td", {}, wake.status),
      h("td", {}, clock(wake.dueAt)),
      h("td", {}, triggerText(wake.trigger)),
      h("td", {}, wake.tries),
      h("td", { class: "warn" }, wake.error ?? ""),
    ),
  );
  section("wakes").replaceChildren(table(["made", "status", "due", "for", "tries", "error"], rows));
}

function renderCalls(calls) {
  if (calls.length === 0) {
    section("model calls").replaceChildren(h("p", { class: "muted" }, "No model call yet."));
    return;
  }
  const rows = calls.map((call) => {
    let outcome = "ok";
    if (!call.ok) outcome = call.failure;
    let firstToken = "";
    if (call.firstTokenMs !== null) firstToken = span(call.firstTokenMs);
    return h(
      "tr",
      {},
      h("td", {}, clock(call.startedAt)),
      h("td", { class: "mono" }, call.model),
      h(
        "td",
        { class: call.ok ? "" : "warn" },
        outcome,
        call.reason ? h("div", { class: "muted" }, call.reason) : null,
      ),
      h("td", {}, firstToken),
      h("td", {}, span(call.totalMs)),
      h("td", {}, `${tokens(call.promptTokens ?? 0)} / ${tokens(call.outputTokens ?? 0)}`),
    );
  });
  section("model calls").replaceChildren(
    h("p", { class: "muted" }, "The latest 50, newest first."),
    table(["started", "model", "outcome", "first token", "took", "tokens in / out"], rows),
  );
}

// --------------------------------------------------------------------- loop --

async function pollState() {
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error(`the monitor answered ${response.status}`);
  state = await response.json();
  skewMs = msOf(state.clock.now) - Date.now();
  renderHeader();
  renderDiagram();
}

async function loop() {
  try {
    await pollState();
    await pollChat(false);
  } catch (error) {
    document.getElementById("phase").textContent = `can't reach the monitor: ${error.message}`;
  }
  setTimeout(loop, POLL_MS);
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && open.id) closeChat();
});
setInterval(renderClock, 1000);

const fromHash = location.hash.slice(1);
if (fromHash) openChat(fromHash);
void loop();
