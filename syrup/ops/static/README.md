# Dashboard frontend — the map

Plain static files served as-is by `syrup/ops/dashboard.py` (a stdlib HTTP
server). **No build step, no framework, no bundler, no dependencies.** Edit these
files to change the UI; edit `dashboard.py` to change the server/API.

- `index.html` — the shell (sidebar nav, `<main>`, chat dock) + the ordered
  `<script>` tags.
- `style.css` — one flat file, `:root` design tokens at the top, light + dark.
- `js/` — the app, split by concern (below).

## The files (`js/`), in load order

They are **classic scripts sharing one global scope** — a `function`/`let`/`const`
in one file is visible to all the others. Order matters in two places: **`i18n.js`
loads first** (every other file calls `tr()` at render time) and **`main.js` runs
the bootstrap and must load last**.

| file | what lives here |
|------|-----------------|
| `i18n.js`    | the 中文/English string catalog (`STR`), `tr()`, `setLang`, `applyStaticI18n` (**loads first**) |
| `util.js`    | `esc`, markdown renderer, core globals (`D`, `editing`), `postJSON`, `reveal` |
| `memory.js`  | inline Memory / SOUL / skill editing actions |
| `models.js`  | `applyModel` (the one `/api/settings` writer), model picker / catalog / pins |
| `render.js`  | formatters + chat card renderers (`stagesRow`/`teleFooter`) + chatlog + streaming + `sendChat` |
| `diagram.js` | `archSVG` (the architecture chart) **and** its live animation (`STAGE`/`hot`/`pollEvents`) |
| `graph.js`   | graph workflows: data-driven topology chart (`graphSVG` from `d.graph.workflows`), the Overview panel (`graphPanel`), and `animateGraphStage` for `graph_*`/`route` events |
| `views.js`   | subtab/db helpers, SQL console, Memory/Tools sub-views, the `VIEWS` router object |
| `compare.js` | the Model arena (`Arena` tab; internals keep the `compare` name) — race one message through several models at once |
| `dock.js`    | chat sessions/history (`loadThreadInto`), model chip, stats toggle |
| `main.js`    | `render`/`refresh` loop, resizers, voice, and the bootstrap (**loads last**) |

Data flows one way: `refresh()` (main.js) fetches `/api/data` into the global
`D`, then `render()` writes `VIEWS[hash](D)` into `#view`. Every mutation
(`applyModel`, `pinModel`, `saveFact`, …) calls `refresh()` when it's done.

## Rules that bite (read before editing)

- **Inline handlers need global names.** Buttons use `onclick="fn()"` in the
  HTML strings the JS generates. `fn` must stay a top-level name in some `js/`
  file. Rename/move a handler and forget its call sites → the button silently
  breaks. `test_static_assets.py` guards this.
- **Every string a person reads goes through `tr("some.key")`.** Never write
  user-facing prose inline — `i18n.js` holds both wordings and
  `test_i18n.py` fails the build on a key that is missing, half-translated, or
  dead. What stays English in *both* languages is this project's **vocabulary**:
  nav labels, page titles, and node names on the charts (Loop, Memory, Gateway,
  Retrieval gate — CONTEXT.md defines each). Explanations switch; names do not.
  The helper is `tr`, not `t`, because `t` is already the parameter name for a
  turn / a tool / a table in three of these files, and a shadowed global fails
  silently at render time.
- **`archSVG` is byte-frozen — do not rewrite the architecture chart.** It emits
  `data-node="…"`/`data-edge="…"` ids that the `STAGE` map (same file) drives the
  live animation from. If you ever change a node/edge id, change it in both
  places. (Both are in `diagram.js` precisely so they stay together.)
- **The graph chart is data-driven — never hand-edit a topology.** `graphSVG`
  renders `Graph.describe()` served in `/api/data`, so the picture is provably
  what the engine runs (`test_graph_topology_payload.py` pins it). To change the
  chart's shape, change the workflow in `syrup/graph/workflows/`. Graph ids are
  namespaced `g-<node>` / `g-<src>-<dst>` so they can never collide with archSVG's.
- **No build step / no framework / no new dependencies.** If you reach for one,
  stop — the whole point is that this reads and runs with nothing installed.
- **No emojis in UI** (project rule). Known pre-existing exception: the `★`/`☆`
  pin stars in `models.js` (typographic dingbats, not colour emoji) — left as-is.

## Verifying a change (no JS test runner exists)

Frontend logic is not unit-tested; verify in the browser preview:
`make dashboard` (or the preview tool) → hard-reload `localhost:9049` → click the
sidebar tabs and the chat dock → check the console shows **zero errors**. The
Python side (`dashboard.py` endpoints, `_thread_history`, pins, session resume)
*is* covered by `evals/deterministic/`.

**A running server does not pick up Python changes.** Static files here (`.js`,
`.css`, `index.html`) are read from disk on every request, so a hard-reload shows
them. But `dashboard.py` and everything it imports are held in memory — after
pulling or editing backend code, **restart `make dashboard`**, or the page renders
new markup against stale data (e.g. a new Settings panel that shows nothing because
the old route isn't sending its fields).
