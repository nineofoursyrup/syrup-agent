// syrup dashboard — subtab/db helpers, SQL console, Memory/Tools sub-views, VIEWS.
// Split out of app.js: classic <script>, shared global scope (no build
// step, no modules). Load order + rules: static/README.md.

// --- sub-tabs: keep long pages short by splitting them into hash-routed tabs
// (#memory/semantic, #database/facts). Each tab is a plain link, so it's
// bookmarkable and the architecture cards can deep-link straight to one.
function subtabBar(view, tabs, active){
  return `<div class="subtabs">${tabs.map(([key,label,n]) =>
    `<a class="subtab ${key===active?"on":""}" href="#${view}/${key}">${esc(label)}${
      n!=null?`<span class="n">${n}</span>`:""}</a>`).join("")}</div>`;
}

// A raw SQLite table, scrollable, with the column names AS the (indigo) sticky
// headers so the schema lines up over its data instead of floating above it.
function dbTable(t){
  if (!t.sample.length) return `<div class="card empty">${esc(tr("db.emptyTable"))}</div>`;
  const head = t.columns.map(c => `<th class="dbcol">${esc(c)}${
    t.types&&t.types[c]?`<small>${esc(t.types[c].toLowerCase())}</small>`:""}</th>`).join("");
  const body = t.sample.map(r => `<tr>${t.columns.map(c =>
    `<td class="dbcell">${esc(String(r[c]??"").slice(0,120))}</td>`).join("")}</tr>`).join("");
  return `<div class="scrolly"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="meta" style="margin-top:6px">${esc(tr("db.showingRows", t.sample.length, t.count))}</div>`;
}
// i18n KEYS, resolved by dbDesc() at render time — a table's one-line "what it
// holds" is an explanation, so it switches language with everything else.
const DB_DESC = {
  calendar_events: "db.descCalendar",
  facts: "db.descFacts",
  episodes: "db.descEpisodes",
  chat_log: "db.descChatLog",
};
const dbDesc = name => DB_DESC[name] ? tr(DB_DESC[name]) : "";
const QUERY_EXAMPLES = [
  "SELECT role, content FROM chat_log ORDER BY id DESC LIMIT 10",
  "SELECT subject, content FROM facts",
  "SELECT session_id, COUNT(*) FROM chat_log GROUP BY session_id",
];
function dbQueryView(){
  return `<div class="meta" style="margin-bottom:10px">${tr("db.sqlBlurb")}</div>
    <textarea class="sqlbox" id="sqlbox" spellcheck="false" onfocus="markEditing()" oninput="markEditing()">${esc(QUERY_EXAMPLES[0])}</textarea>
    <div style="margin:8px 0"><button class="save" onclick="runQuery()">${esc(tr("db.run"))}</button>
      <span class="meta" style="margin-left:12px">${esc(tr("db.try"))}${QUERY_EXAMPLES.map(q=>`<span class="qexample" onclick="qFill(this.textContent)">${esc(q)}</span>`).join(" &nbsp; ")}</span></div>
    <div id="qout"></div>`;
}

// --- read-only SQL console (item: "a simple query editor like Supabase")
function qFill(sql){ const b=document.getElementById("sqlbox"); if(b){ b.value=sql; runQuery(); } }
async function runQuery(){
  editing = true;   // keep the 5s refresh from wiping the query + results
  const sql = (document.getElementById("sqlbox")||{}).value || "";
  const out = document.getElementById("qout");
  out.innerHTML = `<div class="meta">${esc(tr("db.running"))}</div>`;
  const r = await postJSON("/api/query", {sql});
  if (r.error){ out.innerHTML = `<div class="card empty" style="color:var(--bad)">${esc(r.error)}</div>`; return; }
  if (!r.rows.length){ out.innerHTML = `<div class="card empty">${esc(tr("db.zeroRows"))}</div>`; return; }
  out.innerHTML = `<div class="scrolly"><table><thead><tr>${
    r.columns.map(c=>`<th class="dbcol">${esc(c)}</th>`).join("")}</tr></thead><tbody>${
    r.rows.map(row=>`<tr>${row.map(v=>`<td class="dbcell">${esc(String(v).slice(0,120))}</td>`).join("")}</tr>`).join("")
    }</tbody></table></div><div class="meta" style="margin-top:6px">${esc(tr("db.nRows", r.rows.length))}</div>`;
}

// --- Memory sub-tabs. Memory is the friendly, per-pillar view of what persists;
// the Data tab shows the SAME rows as raw SQLite tables (see the explainer).
function memOverview(d){
  const s = d.stats;
  const pillars = [
    [tr("mem.semantic"),"semantic",tr("mem.nFacts",d.facts.length),tr("mem.semDesc")],
    [tr("mem.episodic"),"episodic",tr("mem.nEpisodes",d.episodes.length),tr("mem.epiDesc")],
    [tr("mem.procedural"),"skills",tr("mem.nSkills",d.skills.length),tr("mem.procDesc")],
  ].map(([name,sub,n,desc]) => `<div class="box" style="min-width:0" onclick="location.hash='memory/${sub}'">
      <b>${esc(name)} <span class="meta" style="font-weight:400">· ${esc(n)}</span></b><span>${esc(desc)}</span></div>`).join("");
  return `<div class="card" style="border-color:var(--accent);background:var(--accent-soft)">
      ${tr("mem.vsDb")}
      <div class="r">${tr("mem.vsDbBody", reveal("MEMORY.md","MEMORY.md"))}</div></div>
    <h2>${esc(tr("mem.pillarsH"))}</h2>
    <div class="tiles" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">${pillars}</div>
    <h2>${esc(tr("mem.gateH"))}</h2>${gateSplit(s)}
    <div class="meta" style="margin-top:8px">${tr("mem.gateNote")}</div>
    <div class="meta" style="margin-top:14px">${esc(tr("mem.files"))}${reveal("state.db","state.db")} · ${reveal("MEMORY.md","MEMORY.md")} · ${reveal("SOUL.md","SOUL.md")} · ${reveal("skills","skills/")}</div>`;
}
function memSemantic(d){
  let h = `<div class="meta" style="margin-bottom:12px">${esc(tr("mem.semBlurb"))}</div>`;
  h += `<div class="card" style="padding:4px 8px"><table><tr><th>${esc(tr("mem.thSubject"))}</th><th>${esc(tr("mem.thFact"))}</th><th>${esc(tr("mem.thSource"))}</th><th></th></tr>${
    d.facts.map(f => `<tr id="fact-${f.id}">
      <td><code>${esc(f.subject)}</code></td>
      <td class="fc">${esc(f.content)}</td>
      <td class="meta">${esc(f.source)}</td>
      <td style="white-space:nowrap"><a class="reveal" onclick="editFact(${f.id})">${esc(tr("mem.edit"))}</a> · <a class="reveal del" onclick="delMem('delete_fact',${f.id})">${esc(tr("mem.delete"))}</a></td>
    </tr>`).join("")}</table></div>`;
  return h;
}
function memEpisodic(d){
  const src = d.episodes_source || "sqlite";
  let h = `<div class="meta" style="margin-bottom:8px">${esc(tr("mem.backend"))}<span class="srcpill">${esc(src)}</span></div>`;
  if (d.episodes_error) h += `<div class="card empty">${esc(tr("mem.notionErr", d.episodes_error))}</div>`;
  h += `<div class="card" style="background:var(--accent-soft);border-color:var(--line2)">
    ${tr("mem.whySmall")} <span class="r">${tr("mem.whySmallBody")}</span></div>`;
  h += `<div class="card" style="padding:4px 8px"><table><tr><th>${esc(tr("mem.thDate"))}</th><th>${esc(tr("mem.thEpisode"))}</th><th></th></tr>${
    d.episodes.map(e => `<tr><td class="meta">${esc(e.happened_at)}</td><td>${esc(e.summary)}</td>
      <td><a class="reveal del" onclick="delMem('delete_episode','${e.id}')">${esc(tr("mem.delete"))}</a></td></tr>`).join("")}</table></div>`;
  return h;
}
function memSkills(d){
  let h = `<div class="meta" style="margin-bottom:12px">${tr("mem.skillsBlurb", reveal("skills", tr("mem.skillsFolder")))}</div>`;
  h += d.skills.map((sk,i) => {
    const full = `---
name: ${sk.name}
description: ${sk.description}
---

${sk.body}`;
    return `<div class="card">
      <div class="u"><code>${esc(sk.name)}</code> <span class="meta" style="font-weight:400">· ${esc(sk.description)}</span>
        <span class="srcpill ${sk.editable?"":"apple"}" style="margin-left:6px">${esc(sk.editable?tr("mem.skillHome"):tr("mem.skillBuiltin"))}</span></div>
      <textarea class="editor" id="sk-${i}" style="min-height:150px;margin-top:8px" data-path="${esc(sk.path)}"
        oninput="dirty('sksave-${i}')" onfocus="markEditing()">${esc(full)}</textarea>
      <div style="margin-top:8px"><button class="save" id="sksave-${i}" disabled onclick="saveSkill(${i})">${esc(tr("mem.saveSkill"))}</button>
        <span class="meta" id="skmsg-${i}" style="margin-left:10px">${esc(sk.rel)}</span></div></div>`;
  }).join("") || `<div class="card empty">${esc(tr("mem.noSkills"))}</div>`;
  return h;
}
function memSoul(d){
  return `<div class="meta" style="margin-bottom:12px">${esc(tr("mem.soulBlurb"))}</div>
    <div class="card"><textarea id="soul" class="editor" style="min-height:260px"
      oninput="dirty('soul-save')" onfocus="markEditing()">${esc(d.soul||"")}</textarea>
    <div style="margin-top:8px"><button class="save" id="soul-save" disabled onclick="saveSoul()">${esc(tr("mem.saveSoul"))}</button>
      <span class="meta" id="soul-msg" style="margin-left:10px"></span></div></div>
    <div class="meta" style="margin-top:10px">${reveal("SOUL.md",tr("mem.openSoul"))}</div>`;
}
function memConsolidation(d){
  const distilled = d.facts.filter(f => f.source==="consolidation");
  let h = `<div class="card">${tr("mem.consHow")} <span class="r">${tr("mem.consHowBody", d.consolidate_every)}</span></div>`;
  h += `<div class="tiles" style="margin-top:12px">
    <div class="tile"><b>${d.chat_pending}</b><span>${esc(tr("mem.queued"))}</span></div>
    <div class="tile"><b>${d.consolidate_every*2}</b><span>${esc(tr("mem.threshold"))}</span></div>
    <div class="tile"><b>${distilled.length}</b><span>${esc(tr("mem.factsFromCons"))}</span></div>
    <div class="tile"><b>${d.episodes.length}</b><span>${esc(tr("mem.episodesTotal"))}</span></div></div>`;
  h += `<h2>${esc(tr("mem.distilledH"))}</h2>`;
  h += table([tr("mem.thSubject"),tr("mem.thFact"),tr("mem.thWhen")], distilled.map(f =>
    `<tr><td><code>${esc(f.subject)}</code></td><td>${esc(f.content)}</td><td class="meta">${esc((f.created_at||"").slice(0,10))}</td></tr>`));
  h += `<div class="meta" style="margin-top:10px">${tr("mem.consFooter")}</div>`;
  return h;
}

// Tools ▸ Results: the artifacts tool calls produced (kept distinct from the
// tools themselves — the old tab conflated capability with output).
function toolsResults(d){
  let h = `<div class="meta" style="margin-bottom:10px">${esc(tr("tools.resultsBlurb"))}</div>`;
  h += `<h2>${esc(tr("tools.calendarH"))} <span class="meta" style="font-weight:400">${esc(tr("tools.fromCreate"))}</span></h2>`;
  h += table([tr("tools.thEvent"),tr("tools.thStart"),tr("tools.thEnd"),tr("tools.thWith")], d.calendar.map(e =>
    `<tr><td>${esc(e.title)}</td><td class="meta">${esc(e.start)}</td><td class="meta">${esc(e.end)}</td><td>${esc(e.attendees)}</td></tr>`));
  h += `<div class="meta" style="margin-bottom:16px">${tr("tools.icsNote", reveal("calendar.ics", tr("tools.icsReveal")))}</div>`;
  h += `<h2>${esc(tr("tools.outboxH"))} <span style="font-weight:400;text-transform:none;letter-spacing:0">· ${reveal("outbox",tr("tools.outboxOpen"))}</span></h2>`;
  h += d.outbox.length ? d.outbox.map(o=>`<div class="card"><span class="u">${esc(o.name)}</span><div class="r">${esc(o.text)}</div></div>`).join("")
                       : `<div class="card empty">${esc(tr("tools.outboxEmpty"))}</div>`;
  return h;
}
// Tools ▸ MCP: external connectors. Shows live status + a copy-paste config so
// anyone can plug in their own server (scalable, not a one-off).
function toolsMCP(t){
  const m = t.mcp;
  let h = `<div class="card" style="border-color:${m.live?"var(--good)":"var(--line2)"}">
    <b>${esc(m.live?tr("tools.mcpConnected"):m.configured?tr("tools.mcpConfigured"):tr("tools.mcpNotSetUp"))}</b>
    <div class="r">${tr("tools.mcpBody")} ${m.configured
      ? `${tr("tools.mcpServers", m.servers.map(s=>`<code>${esc(s)}</code>`).join(" "))}${m.live?"":esc(tr("tools.mcpStartChat"))}`
      : esc(tr("tools.mcpNone"))}</div></div>`;
  h += `<h2>${esc(tr("tools.mcpConnectH"))}</h2><div class="card">
    <div class="meta">${esc(tr("tools.mcpStep1"))}<code>pip install -e '.[mcp]'</code></div>
    <div class="meta" style="margin-top:6px">${tr("tools.mcpStep2", reveal("", tr("tools.mcpFolder")))}</div>
    <pre style="font-family:var(--mono);font-size:11.5px;color:var(--ink2);white-space:pre-wrap;margin-top:8px">{"servers": [
  {"name": "fs", "command": "npx",
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "${esc(D&&D.home||"")}"]}
]}</pre>
    <div class="meta" style="margin-top:8px">${tr("tools.mcpStep3")}</div></div>`;
  h += `<div class="meta" style="margin-top:12px">${tr("tools.mcpScales", reveal("skills","skills/"))}</div>`;
  return h;
}

function connectionField(key, field, prefix="connection"){
  const id = `${prefix}-${key}-${field.name}`;
  const label = `${esc(field.label)}${field.required?" *":""}`;
  const help = field.help ? `<div class="conn-field-help">${esc(field.help)}</div>` : "";
  if (field.kind === "bool") return `<div class="conn-field">
    <label class="conn-check" for="${id}"><input id="${id}" data-field="${esc(field.name)}" type="checkbox" ${field.value?"checked":""}>
      <span>${label}</span></label>${help}</div>`;
  if (field.kind === "choice") return `<div class="conn-field"><label class="fld" for="${id}"><span>${label}</span>
    <select id="${id}" data-field="${esc(field.name)}">${field.options.map(o=>`<option value="${esc(o)}" ${o===field.value?"selected":""}>${esc(o)}</option>`).join("")}</select>
    </label>${help}</div>`;
  const configured = field.secret && field.configured
    ? ` <span class="conn-secret-state">set ····${esc(field.last4)}</span>` : "";
  const clear = field.secret && field.configured
    ? `<label class="conn-clear"><input type="checkbox" data-clear="${esc(field.name)}"> ${esc(tr("conn.clearSaved"))}</label>` : "";
  return `<div class="conn-field"><label class="fld" for="${id}"><span>${label}${configured}</span>
    <input id="${id}" data-field="${esc(field.name)}" type="${field.secret?"password":"text"}"
      value="${field.secret?"":esc(field.value)}" placeholder="${field.secret?(field.configured?esc(tr("conn.blankKeeps")):esc(tr("conn.notConfigPh"))):""}">
    </label>${clear}${help}</div>`;
}
async function saveConnection(key, force){
  const modal = document.querySelector(`.connmodal[data-connection="${key}"]`), values = {}, clear = [];
  if (!modal) return;
  modal.querySelectorAll("[data-field]").forEach(el => values[el.dataset.field] = el.type === "checkbox" ? (el.checked ? "1" : "") : el.value);
  modal.querySelectorAll("[data-clear]").forEach(el => { if (el.checked) clear.push(el.dataset.clear); });
  const msg = document.getElementById(`connection-msg-${key}`);
  msg.textContent = force ? tr("conn.savingForce") : tr("conn.saving");
  const r = await postJSON("/api/connections", {key, values, clear, force:!!force});
  if (!r.ok && r.can_force) {
    msg.innerHTML = `${esc(r.error)} <button class="save ghost conn-force" onclick="saveConnection('${esc(key)}',true)">${esc(tr("conn.saveAnyway"))}</button>`;
  } else if (!r.ok) {
    msg.textContent = r.error || tr("conn.failed");
  } else {
    closeConnectionModal();
    await refresh();
  }
}
async function testConnection(key){
  const msg = document.getElementById(`connection-msg-${key}`);
  if (msg) msg.textContent = tr("conn.testing");
  const r = await postJSON("/api/connections/test", {key});
  if (!r.status) {
    if (msg) msg.textContent = r.error || tr("conn.failed");
    return;
  }
  const display = connectionStatusDisplay(r.status);
  const status = document.getElementById("connection-modal-status");
  if (status) {
    status.className = `connstatus ${display.className}`;
    status.innerHTML = `<span class="conndot"></span>${esc(display.label)}`;
  }
  const detail = document.getElementById("connection-modal-status-detail");
  if (detail) detail.textContent = r.status.message || "";
  const checked = document.getElementById("connection-modal-checked");
  if (checked) checked.textContent = r.status.checked_at ? tr("conn.lastChecked", r.status.checked_at) : "";
  if (msg) msg.textContent = r.status.message || display.label;
  await refresh();
}
async function saveProvider(provider){
  const info = (D.providers || []).find(x => x.key === provider);
  const field = info && info.fields[0] && document.getElementById(`provider-${provider}-${info.fields[0].name}`);
  const payload = {provider};
  if (field && field.value) payload.key = field.value;
  // Models are global fields for the *current* provider. Switching cards must
  // omit them so apply_provider selects the new provider's own default.
  if (provider === stProvider()) {
    const model = document.getElementById("provider-model"), small = document.getElementById("provider-small-model"), base = document.getElementById("provider-base-url"), custom = document.getElementById("provider-custom-key");
    if (model) payload.model = model.value;
    if (small) payload.small_model = small.value;
    if (base) payload.base_url = base.value;
    if (custom && custom.value) payload.custom_key = custom.value;
    if (document.getElementById("provider-clear-custom-key")?.checked) payload.custom_key = "";
  }
  const r = await postJSON("/api/providers", payload);
  if (!r.ok) alert(r.error || "Provider update failed"); else refresh();
}
function stProvider(){ return (D.settings || {}).provider || "anthropic"; }

const CONNECTION_GROUPS = ["Channels", "Productivity", "Memory", "Tools"];
// "Memory", not "Storage". The registry already calls this group "Memory &
// Storage"; the display map was dropping the half that says what these
// actually are. Notion is the episodic store, Supabase the semantic one, and
// every hosted memory service that joins them is semantic too — none of it is
// generic storage, and Memory is one of the four pillars the rest of the
// dashboard is organised around.
const CONNECTION_GROUP_MAP = {
  "Channels": "Channels",
  "Calendar & Productivity": "Productivity",
  "Memory & Storage": "Memory",
  "Search & Observability": "Tools",
};

function connectionDisplayGroup(item){
  if (item.key === "apple_tools") return "Tools";
  return CONNECTION_GROUP_MAP[item.group] || "Tools";
}

// The four group names above are IDENTIFIERS — they key the grouping and are
// pinned by test_static_assets.py, so they stay English in the code. This is
// the separate step that turns one into a heading a reader sees.
const CONNECTION_GROUP_LABELS = {Channels:"conn.grpChannels", Productivity:"conn.grpProductivity",
                                 Memory:"conn.grpMemory", Tools:"conn.grpTools"};
const connectionGroupLabel = g => CONNECTION_GROUP_LABELS[g] ? tr(CONNECTION_GROUP_LABELS[g]) : g;

function connectionStatusDisplay(status){
  const state = (status && status.state) || "not_configured";
  if (state === "connected") return {label:tr("conn.connected"), className:"connected"};
  if (state === "error") return {label:tr("conn.error"), className:"error"};
  // "configured" means every required field is filled and the extra is
  // installed — it just hasn't been probed. That is not a warning, so it must
  // not wear the amber "needs setup" pill: this state covers most of a working
  // setup on first visit, and colouring it like a problem told every new user
  // their Telegram, Notion and Tavily needed fixing when they were fine.
  if (state === "configured") return {label:tr("conn.configured"), className:"configured"};
  if (state === "installed_but_unconfigured") return {label:tr("conn.needsSetup"), className:"needs-setup"};
  return {label:tr("conn.notConfigured"), className:"not-configured"};
}

function connectionCard(item){
  const display = connectionStatusDisplay(item.status);
  const action = item.status && item.status.state !== "not_configured" ? tr("conn.edit") : tr("conn.configure");
  // Say WHY on the card. "needs setup" covers two unrelated fixes — a missing
  // value ("missing NOTION_TOKEN") and a missing package ("missing notion
  // extra", which wants a pip install, not a key) — and the reason used to be
  // hidden until you opened the modal. The message repeats the label for
  // connected/configured, so only show it where it adds something.
  const why = (item.status && item.status.message
    && (item.status.state === "installed_but_unconfigured" || item.status.state === "error"))
    ? `<div class="connwhy">${esc(item.status.message)}</div>` : "";
  return `<article class="provcard conncard" data-connection-card="${esc(item.key)}">
    <img class="provlogo connlogo" src="/static/logos/connections/${esc(item.key)}.svg" alt="">
    <div class="provname">${esc(item.name)}</div>
    <div class="connstatus ${display.className}"><span class="conndot"></span>${esc(display.label)}</div>
    ${why}
    <div class="conndesc">${esc(item.what)}</div>
    <div class="provactions connactions">
      <button class="save ghost" onclick="openConnectionModal('${esc(item.key)}')">${esc(action)}</button>
    </div>
  </article>`;
}

function connectionsGrid(items){
  const grouped = Object.fromEntries(CONNECTION_GROUPS.map(group => [group, []]));
  items.forEach(item => grouped[connectionDisplayGroup(item)].push(item));
  return CONNECTION_GROUPS.map(group => `<section class="connsection">
    <h2>${esc(connectionGroupLabel(group))}</h2>
    <div class="provgrid conngrid">${grouped[group].map(connectionCard).join("")}</div>
  </section>`).join("") + `<div id="connection-modal-root"></div>`;
}

function openConnectionModal(key){
  const item = ((D && D.connections) || []).find(connection => connection.key === key);
  const root = document.getElementById("connection-modal-root");
  if (!item || !root) return;
  markEditing();
  const display = connectionStatusDisplay(item.status);
  const status = item.status || {};
  const fields = item.fields.map(field => connectionField(item.key, field)).join("");
  root.innerHTML = `<div class="connmodal-back" onclick="closeConnectionModal()" onkeydown="connectionModalKeydown(event)">
    <section class="connmodal" data-connection="${esc(item.key)}" role="dialog" aria-modal="true" aria-labelledby="connection-modal-title" onclick="event.stopPropagation()">
      <header class="connmodal-head">
        <img class="provlogo connlogo" src="/static/logos/connections/${esc(item.key)}.svg" alt="">
        <div class="connmodal-title">
          <h3 id="connection-modal-title">${esc(item.name)}</h3>
          <div class="connstatus ${display.className}" id="connection-modal-status"><span class="conndot"></span>${esc(display.label)}</div>
        </div>
        <button class="connmodal-close" type="button" onclick="closeConnectionModal()" aria-label="${esc(tr("conn.close"))}">${esc(tr("conn.close"))}</button>
      </header>
      <p class="conndesc connmodal-desc">${esc(item.what)}</p>
      <div class="connmodal-meta">
        <span id="connection-modal-status-detail">${esc(status.message || "")}</span>
        <span id="connection-modal-checked">${status.checked_at?esc(tr("conn.lastChecked", status.checked_at)):""}</span>
      </div>
      ${(item.install_command || item.setup_url) ? `<div class="connsetup">
        ${item.install_command?`<code>${esc(item.install_command)}</code>`:""}
        ${item.setup_url?`<a href="${esc(item.setup_url)}" target="_blank" rel="noopener noreferrer">${esc(tr("conn.setupGuide"))}</a>`:""}
      </div>` : ""}
      <div class="connection-fields">${fields}</div>
      <footer class="connmodal-actions">
        <button class="save" onclick="saveConnection('${esc(item.key)}')">${esc(tr("conn.save"))}</button>
        <button class="save ghost" onclick="testConnection('${esc(item.key)}')">${esc(tr("conn.test"))}</button>
        <span class="connmodal-message" id="connection-msg-${esc(item.key)}" aria-live="polite"></span>
      </footer>
    </section>
  </div>`;
  setTimeout(() => {
    const target = root.querySelector(".connection-fields input, .connection-fields select")
      || root.querySelector(".connmodal-close");
    target?.focus();
  }, 0);
}

function closeConnectionModal(){
  editing = false;
  const root = document.getElementById("connection-modal-root");
  if (root) root.innerHTML = "";
  if (activeView === "connections") render();
}

function connectionModalKeydown(event){
  if (event.key === "Escape") closeConnectionModal();
}

const VIEWS = {
  models(d){
    // Provider card grid (logo / status dot / edit / enable-disable). Editing
    // happens in a modal opened from a card; both live in js/models.js.
    return modelsGrid(d);
  },
  connections(d){
    const items = d.connections || [];
    return items.length ? connectionsGrid(items) : `<div class="card empty">${esc(tr("conn.none"))}</div>`;
  },
  // Gateway: ONE unified conversation across every channel (dashboard, telegram,
  // voice, cli) — the same loop + memory answer all of them. Each message is
  // tagged with where it came in, Hermes-style. You type in the dock on the right.
  // Gateway = an INBOX of conversations (like Slack/Intercom): one row per
  // conversation, tagged with its channel(s). Click one to open it in the chat
  // dock (the active thread). No longer a flat stream that duplicates the dock.
  gateway(d){
    const sessions = d.sessions || [];
    let h = `<div class="meta" style="margin-bottom:14px">${tr("gw.blurb")}</div>`;
    if (!sessions.length)
      return h + `<div class="card empty">${tr("gw.empty")}</div>`;
    h += sessions.map(s => {
      const tags = gwTags(s);
      const on = s.id === SESSION;
      return `<div class="toolcard" style="cursor:pointer${on?';border-color:var(--accent)':''}" onclick="openConversation('${esc(s.id)}')">
        <div class="tn" style="display:flex;justify-content:space-between;align-items:baseline;gap:10px">
          <span>${esc(s.title||s.id)} ${tags}</span>
          <span class="meta" style="font-weight:400;white-space:nowrap">${sessionMeta(s)}</span></div>
        <div class="td">${esc(s.last||"")}</div></div>`;
    }).join("");
    return h;
  },
  overview(d){
    const s = d.stats;
    const u = d.usage || {total_cost:0};
    const tiles = [
        [money(u.total_cost),tr("ov.spent"),"money"],[secs(s.latency_avg),tr("ov.avgTurn"),""],
        [s.turns,tr("ov.turns"),""],[s.tool_calls,tr("ov.toolCalls"),""],
        [d.facts.length,tr("ov.facts"),""],[d.calendar.length,tr("ov.events"),""],
      ].map(([v,l,c])=>`<div class="tile"><b class="${c}">${v}</b><span>${esc(l)}</span></div>`).join("");
    return `<div class="tiles">${tiles}</div>
    <h2>${esc(tr("ov.gateH"))}</h2>${gateSplit(s)}
    <h2 style="margin-top:26px">${esc(tr("ov.archH"))} <span class="arch-status"></span></h2>
    ${archSVG(d)}
    <h2>${esc(tr("ov.graphH"))}</h2>
    ${graphPanel(d)}
    <h2>${esc(tr("ov.latestH"))}</h2>${d.turns.length?turnCard(d.turns[0]):`<div class="card empty">${esc(tr("ov.noTurns"))}</div>`}`;
  },
  loop(d){
    return d.turns.length ? d.turns.map(turnCard).join("") : `<div class="card empty">${esc(tr("loop.empty"))}</div>`;
  },
  // Graph workflows: the loop's sibling. The chart is rendered from the
  // engine's own describe() (served in d.graph.workflows) so it can never
  // show a shape the engine doesn't run. Nothing here is a mode switch —
  // the harness routes every message itself; this tab just tells the story.
  graph(d){
    const g = d.graph || {enabled:false, workflows:[], stats:{quick:0, full:0}};
    let h = `<div class="meta" style="margin-bottom:14px">${tr("graph.blurb")}</div>`;
    if (!g.enabled)
      h += `<div class="card">${tr("graph.off")}
        <div class="meta" style="margin-top:6px">${tr("graph.offHow")}</div></div>`;
    // The two workflows are two different JOBS with different triggers, which is
    // the thing the page has to make obvious — otherwise two stacked charts read
    // like two options you pick between.
    const NOTE = {triage: tr("graph.noteTriage"), gather: tr("graph.noteGather")};
    (g.workflows || []).forEach(w => {
      if (!w) return;
      h += `<h2>${esc(tr("graph.liveTopology", w.name))} <span class="arch-status"></span></h2>`;
      const tot = g.stats.quick + g.stats.full;
      const extra = w.name === "triage" && tot
        ? esc(tr("graph.soFar", g.stats.quick, g.stats.full)) : "";
      h += `<div class="card">${graphSVG(w)}
        <div class="meta" style="margin-top:8px">${NOTE[w.name] || ""}${extra} ·
        ${tr("graph.fromDescribe")}</div></div>`;
      if (w.name === "gather") h += graphRunPanel();
    });
    const gturns = (d.turns||[]).filter(t => t.graph && t.graph.route);
    h += `<h2>${esc(tr("graph.turnsH"))}</h2>`;
    h += gturns.length
      ? gturns.slice(0,20).map(t => `<div class="card">
          <div class="u">${esc(t.user_message)}</div>
          <div class="meta" style="margin-top:4px"><span class="badge ${t.graph.route==="quick"?"":"retrieve"}">${esc(tr("atom.graphStage", t.graph.route))}</span>
            <span class="meta" style="margin:0">${esc(t.graph.reason||"")}</span></div>
          <div class="r">${renderMarkdown(t.reply||"")}</div></div>`).join("")
      : `<div class="card empty">${esc(g.enabled ? tr("graph.noTurnsOn") : tr("graph.noTurnsOff"))}</div>`;
    return h;
  },
  memory(d, sub){
    sub = sub || "overview";
    const tabs = [["overview",tr("mem.tabOverview")],["semantic",tr("mem.tabSemantic"),d.facts.length],
      ["episodic",tr("mem.tabEpisodic"),d.episodes.length],["skills",tr("mem.tabSkills"),d.skills.length],
      ["soul",tr("mem.tabSoul")],["consolidation",tr("mem.tabCons"),d.chat_pending]];
    let h = subtabBar("memory", tabs, sub);
    if (sub==="semantic") return h + memSemantic(d);
    if (sub==="episodic") return h + memEpisodic(d);
    if (sub==="skills") return h + memSkills(d);
    if (sub==="soul") return h + memSoul(d);
    if (sub==="consolidation") return h + memConsolidation(d);
    return h + memOverview(d);
  },
  settings(d){
    const st = d.settings || {providers:[]};
    return `<h2>${esc(tr("set.expH"))}</h2><div class="card">
      <div class="meta" style="margin-bottom:8px">${esc(tr("set.expBlurb"))}</div>
      <label class="fld">${esc(tr("set.expLabel"))}<select id="set-experimental" onfocus="markEditing()">
        <option value="" ${!st.experimental?"selected":""}>${esc(tr("set.off"))}</option>
        <option value="1" ${st.experimental?"selected":""}>${esc(tr("set.on"))}</option>
      </select></label>
      <button class="save" onclick="saveSettings()">${esc(tr("set.save"))}</button><span class="meta" id="set-msg"></span></div>
    <h2>${esc(tr("set.graphH"))}</h2><div class="card">
      <div class="meta" style="margin-bottom:8px">${tr("set.graphBlurb")}</div>
      <label class="fld">${esc(tr("set.graphLabel"))}
        <select id="set-graph-workflows" onfocus="markEditing()">
          <option value="" ${!st.graph_workflows?"selected":""}>${esc(tr("set.graphOff"))}</option>
          <option value="1" ${st.graph_workflows?"selected":""}>${esc(tr("set.graphOn"))}</option>
        </select></label>
      <div style="margin-top:12px"><button class="save" onclick="saveSettings()">${tr("set.saveSwitch")}</button>
        <span class="meta" style="margin-left:10px">${esc(tr("set.noRestart"))}</span></div>
    </div>`;
  },
  tools(d, sub){
    const t = d.tools || {catalog:[], mcp:{configured:false,servers:[],live:false}, apple_on:false};
    sub = sub || "available";
    const tabs = [["available",tr("tools.tabAvailable"),t.catalog.length],["results",tr("tools.tabResults")],
      ["mcp",tr("tools.tabMcp"),t.mcp.servers.length||null]];
    let h = subtabBar("tools", tabs, sub);
    if (sub === "results") return h + toolsResults(d);
    if (sub === "mcp") return h + toolsMCP(t);
    // Available: what the agent CAN do (grouped by origin), not just what it did.
    h += `<div class="meta" style="margin-bottom:12px">${esc(tr("tools.blurb"))}
      ${t.apple_on?"":tr("tools.appleOff")}${tr("tools.connectMore")}</div>`;
    const SRC = [["flagship",tr("tools.srcFlagship")],["web",tr("tools.srcWeb")],
      ["self-management",tr("tools.srcSelf")],
      ["apple",tr("tools.srcApple")],["mcp",tr("tools.srcMcp")],["other",tr("tools.srcOther")]];
    SRC.forEach(([key,label]) => {
      const items = t.catalog.filter(c => c.source === key);
      if (!items.length) return;
      h += `<h2>${esc(label)}</h2>`;
      h += items.map(c => `<div class="toolcard">
        <div class="tn">${esc(c.name)}<span class="srcpill ${key==="mcp"?"mcp":key==="apple"?"apple":""}">${esc(key)}</span></div>
        <div class="td">${esc(c.description)}</div></div>`).join("");
    });
    // Roadmap: whiteboard boxes not wired in yet — set expectations, don't over-promise.
    if ((t.planned||[]).length){
      h += `<h2>${esc(tr("tools.soonH"))} <span class="meta" style="font-weight:400">${tr("tools.soonSub")}</span></h2>`;
      h += t.planned.map(p => `<div class="toolcard" style="opacity:.7">
        <div class="tn">${esc(p.name)}<span class="srcpill apple">${esc(tr("tools.soonPill", p.box))}</span></div>
        <div class="td">${esc(p.description)}</div></div>`).join("");
    }
    return h;
  },
  database(d, sub){
    // The persistence layer itself — one SQLite file, real tables, FTS5 index.
    // "Data" in the nav (plainer than "state.db"), but we keep saying state.db
    // because that's literally the filename you can open.
    const db = d.db || {tables:[], all_tables:[], fts:[], size:0, path:""};
    const tables = db.tables || [];
    sub = sub || "overview";
    const tabs = [["overview",tr("db.tabOverview")],
      ...tables.map(t => [t.name, t.name, t.count]),
      ["query",tr("db.tabQuery")]];
    let h = subtabBar("database", tabs, sub);
    if (sub === "query") return h + dbQueryView();
    if (sub !== "overview"){
      const t = tables.find(x => x.name === sub);
      if (!t) return h + `<div class="card empty">${esc(tr("db.noSuchTable"))}</div>`;
      const notionNote = (t.name === "episodes" && d.episodes_source === "notion")
        ? `<div class="meta" style="margin-bottom:10px">${tr("db.notionNote")}</div>` : "";
      return h + notionNote + `<div class="meta" style="margin-bottom:10px">${esc(dbDesc(t.name))}</div>` + dbTable(t);
    }
    const kb = (db.size/1024).toFixed(1);
    h += `<div class="card" style="border-color:var(--accent);background:var(--accent-soft)">
      ${tr("db.vsMem")} <span class="r">${tr("db.vsMemBody")}</span></div>`;
    h += `<div class="card">
      <div class="u" style="font-family:var(--mono);font-size:12.5px;word-break:break-all">${esc(db.path)}</div>
      <div class="meta">${tr("db.onDisk", kb)}</div>
      <div class="meta" style="margin-top:8px">${reveal("state.db",tr("db.revealDb"))} &nbsp;·&nbsp; ${reveal("",tr("db.openFolder"))}</div></div>`;
    h += `<h2>${esc(tr("db.tablesH"))}</h2>`;
    h += table([tr("db.thTable"),tr("db.thRows"),tr("db.thHolds")], tables.map(t =>
      `<tr><td><a class="reveal" onclick="location.hash='database/${esc(t.name)}'"><code>${esc(t.name)}</code></a></td>
        <td class="meta">${t.count}</td><td class="meta">${esc(dbDesc(t.name))}</td></tr>`));
    h += `<h2>${esc(tr("db.ftsH"))}</h2><div class="card">${tr("db.ftsBody")}
      <div class="meta" style="margin-top:8px">${esc(tr("db.allTables", db.all_tables.length))}${db.all_tables.map(t=>`<code>${esc(t)}</code>`).join(" ")}</div></div>`;
    return h;
  },
  ops(d){
    const s = d.stats;
    const u = d.usage || {calls:0,total_in:0,total_out:0,total_cost:0,by_day:[],by_provider:[]};
    let h = `<div class="tiles">${[
        [money(u.total_cost),tr("ov.spent"),"money"],[u.total_in.toLocaleString(),tr("ops.tokensIn"),""],
        [u.total_out.toLocaleString(),tr("ops.tokensOut"),""],[u.calls.toLocaleString(),tr("ops.llmCalls"),""],
        [secs(s.latency_avg),tr("ov.avgTurn"),""],[`${s.tool_errors}`,tr("ops.toolErrors"),""],
      ].map(([v,l,c])=>`<div class="tile"><b class="${c}">${v}</b><span>${esc(l)}</span></div>`).join("")}</div>`;

    h += `<h2>${esc(tr("ops.spendH"))} <span class="meta" style="font-weight:400">${esc(tr("ops.spendSub"))}</span></h2>`;
    h += `<div class="card"><span class="r">${tr("ops.spendBody", reveal("usage.jsonl", tr("ops.openUsage")))}</span></div>`;
    if ((u.by_provider||[]).length){
      h += table([tr("ops.thProvider"),tr("ops.thLlmCalls"),tr("ops.thIn"),tr("ops.thOut"),tr("ops.thCost")], u.by_provider.map(p =>
        `<tr><td><code>${esc(p.provider)}</code></td><td class="meta">${p.calls}</td>
          <td class="meta">${p.in.toLocaleString()}</td><td class="meta">${p.out.toLocaleString()}</td>
          <td class="meta">${money(p.cost)}</td></tr>`));
    }
    if ((u.by_day||[]).length){
      h += `<h2>${esc(tr("ops.perDayH"))}</h2>`;
      h += table([tr("ops.thDay"),tr("ops.thLlmCalls"),tr("ops.thIn"),tr("ops.thOut"),tr("ops.thCost")], u.by_day.map(r =>
        `<tr><td class="meta">${esc(r.date)}</td><td class="meta">${r.calls}</td>
          <td class="meta">${r.in.toLocaleString()}</td><td class="meta">${r.out.toLocaleString()}</td>
          <td class="meta">${money(r.cost)}</td></tr>`));
    }

    h += `<h2>${esc(tr("ops.gateH"))}</h2>${gateSplit(s)}`;
    const decided = d.turns.filter(t => t.gate);
    if (decided.length){
      h += `<div class="meta" style="margin:8px 0">${esc(tr("ops.gateDecisions"))}</div>`;
      h += table([tr("ops.thTurn"),tr("ops.thDecision"),tr("ops.thWhy")], decided.slice(0,10).map(t =>
        `<tr><td>${esc((t.user_message||"").slice(0,44))}</td>
          <td><span class="pill ${t.gate.decision==="skip"?"skip":"pass"}">${esc(t.gate.decision)}</span></td>
          <td class="meta">${esc(t.gate.reason||"")}</td></tr>`));
    }

    h += `<h2>${esc(tr("ops.releaseH"))} <span class="meta" style="font-weight:400">${esc(tr("ops.releaseSub"))}</span></h2>`;
    h += `<div class="card"><span class="r">${tr("ops.releaseBody")}</span></div>`;
    h += d.eval_report ? `<div class="card">
        <span class="pill ${d.eval_report.deterministic}">deterministic · ${d.eval_report.deterministic}</span>
        <span class="pill ${d.eval_report.judge==="pass"?"pass":d.eval_report.judge==="fail"?"fail":"skip"}" style="margin-left:8px">llm-judge · ${d.eval_report.judge}</span>
        <div class="meta">${tr("ops.lastRun", esc(d.eval_report.ran_at))}</div></div>`
      : `<div class="card empty">${tr("ops.neverRun")}</div>`;

    if ((d.eval_history||[]).length){
      const cnt = s => s ? tr("ops.passFail", s.passed||0, s.failed||0) : "—";
      h += `<h2>${esc(tr("ops.historyH"))}</h2>`;
      h += table([tr("mem.thWhen"),"deterministic","llm-judge",tr("ops.thPassFail")], d.eval_history.map(r =>
        `<tr><td class="meta">${esc((r.ran_at||"").replace("T"," ").slice(0,19))}</td>
         <td><span class="pill ${r.deterministic}">${esc(r.deterministic)}</span></td>
         <td><span class="pill ${r.judge==="pass"?"pass":r.judge==="fail"?"fail":"skip"}">${esc(r.judge)}</span></td>
         <td class="meta">det ${esc(cnt(r.suites&&r.suites.deterministic))} · judge ${esc(cnt(r.suites&&r.suites.judge))}</td></tr>`));
    }

    h += `<h2>${esc(tr("ops.slowestH"))}</h2>`;
    const slow = [...d.turns].filter(t=>t.latency_ms!=null).sort((a,b)=>b.latency_ms-a.latency_ms).slice(0,6);
    h += table([tr("ops.thTurn"),tr("ops.thLatency"),tr("ops.thCost"),tr("ops.thTools")], slow.map(t =>
      `<tr><td>${esc((t.user_message||"").slice(0,48))}</td><td class="meta">${secs(t.latency_ms)}</td><td class="meta">${money(t.cost||0)}</td><td class="meta">${(t.tools||[]).map(x=>x.tool).join(", ")||"—"}</td></tr>`));

    h += `<h2>${esc(tr("ops.tracingH"))} <span class="meta" style="font-weight:400">${esc(tr("ops.tracingSub"))}</span></h2>`;
    if ((d.trace_errors||[]).length){
      h += d.trace_errors.map(e => `<div class="card"><span class="pill fail">${esc(tr("ops.traceEncErr"))}</span>
        <div class="meta" style="margin-top:8px"><code>${esc(e.file)}</code> — ${esc(e.error)}</div></div>`).join("");
    }
    h += `<div class="card"><span class="r">${tr("ops.traceFiles", s.trace_files)}${
      d.trace_file?tr("ops.traceNewest", esc(d.trace_file)):""}. ${reveal("traces",tr("ops.openTraces"))}.
      ${tr("ops.traceIs")}</span></div>`;
    h += (d.trace_tail||[]).length ? table([tr("ops.thEvent"),tr("ops.thDetail"),tr("mem.thWhen")], d.trace_tail.map(e =>
        `<tr><td><code>${esc(e.type)}</code></td><td class="meta">${esc(String(e.detail).slice(0,60))}</td>
          <td class="meta">${esc((e.ts||"").replace("T"," ").slice(0,19))}</td></tr>`))
      : `<div class="card empty">${esc(tr("ops.noTraceLines"))}</div>`;
    h += `<div class="meta" style="margin-top:8px">${tr("ops.waterfalls")}</div>`;

    if (d.wake_scans.length){
      h += `<h2>${esc(tr("ops.wakeH"))}</h2>`;
      h += table([tr("ops.thHeard"),tr("mem.thWhen")], d.wake_scans.map(w =>
        `<tr><td>${esc(w.heard)}</td><td class="meta">${esc((w.ts||"").replace("T"," ").slice(0,19))}</td></tr>`));
    }
    return h;
  },
};
