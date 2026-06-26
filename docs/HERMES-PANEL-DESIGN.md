# Hermes panel — design spec

> **Status:** design draft (planning). No code written yet.
> **Scope:** rename the *Operator* tab → **Hermes**, and turn it into an
> advanced control center where the user builds websites/apps with
> **specialized AI agents** (one per stack family), creates new agents,
> and lets Hermes *learn* across projects — wired through the existing
> **autoskills + UI/UX Pro Max + MCP catalog** machinery.

This is the blueprint we execute against. Nothing here is final until the
phased plan (§9) is approved per-phase.

---

## 1. Vision

Pcreative Studio already scaffolds 77 stacks and drives them with AI coding
agents. The Hermes tab elevates that into an **agent platform**:

- **Hermes = a web-design specialist** that knows every Pcreative Studio stack.
- The user picks a **specialized sub-agent** ("Shopify Liquid expert",
  "WordPress block-theme expert", "Magento+Hyvä expert", …) — or lets
  Hermes auto-pick — and builds a marketplace-ready site/app.
- The user can **create their own agents** (a guided form writes a Hermes
  `SKILL.md`); Hermes can even draft one with AI.
- Hermes **learns**: per-project `.hermes.md` + global memories accumulate
  what worked, so each subsequent build is better.
- Everything reuses the systems we already built — **autoskills**,
  **UI/UX Pro Max**, the **MCP catalog**, the **licensing scaffold**,
  the **market analyzer** — exposed as MCP tools Hermes can call.

### Why Hermes (not a homemade orchestrator)
Hermes v0.15.0 ("The Velocity Release") already ships, *natively*, the
hard parts we'd otherwise build ourselves:

| We need | Hermes already has |
|---|---|
| Parallel variants with isolation | `hermes kanban swarm` (parallel workers → verifier → synthesizer, **worktree-per-task**, **per-task model override**) |
| Scheduled missions | `hermes cron create "every Mon 9am" "…"` (23 delivery platforms) |
| Custom agents that persist + improve | Skills system (`~/.hermes/skills/**/SKILL.md`) + self-improvement loop + memories |
| Group of skills under one command | Skill **bundles** (`~/.hermes/skill-bundles/<slug>.yaml`, invoked `/<slug>`) |
| A web admin UI | `hermes dashboard --tui` → React 19 SPA on `127.0.0.1:9119` (Status / Config / Env / embedded Chat) |
| Provider fallback | `hermes fallback` |
| Multi-model, no lock-in | 200+ models via OpenRouter etc. |

**Design principle:** *don't reimplement what Hermes ships.* We wrap and
embed Hermes features; we only build the **Pcreative Studio-specific layer**
(specialist agents, the MCP action tools, the GUI shell).

---

## 2. Current state (what exists today)

- **`operator_panel.py`**
  - `OperatorPanel` — the tab: brief + variants spinbox + provider combo
    (`codex/opencode/claude-api/gemini`, hardcoded) + log + live preview +
    `HermesTerminal` chat sub-tab.
  - `OperatorMissionDialog` — "automate an existing gallery project".
  - `ProjectPreviewWidget`, `HermesTerminal`.
  - Launches `hermes chat -q <prompt> -s pcreative-studio-operator`.
- **`mcp_server.py`** — 10 MCP tools (read-mostly + 2 writes):
  `list_stacks`, `list_themes`, `list_recent_projects`,
  `list_supported_providers`, `estimate_cost`, `suggest_stack`,
  `run_preflight`, `build_zip`, `create_project`, `run_agent_build`.
- **`~/.hermes/skills/pcreative-studio/pcreative-studio-operator/SKILL.md`** — the one
  orchestration skill (references a non-existent `delegate_task` — bug).
- **Hermes local: v0.14.0** (256 commits behind v0.15.0 → `hermes update`).
- MCP `pcreative-studio` registered + enabled in `~/.hermes/config.yaml`.

### Known gaps / bugs to fix in passing
- SKILL.md promises `delegate_task` that does not exist → replace with
  real `hermes kanban swarm` flow.
- Provider combo is a hardcoded list of 4, not the real 7 of
  `ai_providers.py`, and ignores which provider is *active*.
- "Max 3 QA fixes" baked into the prompt string, not a UI control.
- No visibility of Hermes/MCP/OpenRouter health.
- No notion of *specialized agents* — every mission flies blind on stack.

---

## 3. Information architecture — the Hermes tab

A `QTabWidget` with sub-tabs (left-to-right):

```
┌─ 🤖 Hermes ─────────────────────────────────────────────────────────────┐
│  🚀 Misión │ 🤖 Agentes │ ➕ Crear agente │ 🧠 Memoria │ 📊 Kanban │ ⏰ Cron │ ⚙️ Admin │ 💬 Chat │
├──────────────────────────────────────────────────────────────────────────┤
│  (sub-tab content)                                                         │
└──────────────────────────────────────────────────────────────────────────┘
```

A persistent **status strip** sits above the sub-tabs (always visible):

```
 [⏻ Encender Hermes] │ Hermes v0.15.0 ✓   MCP pcreative-studio ✓   openrouter · claude-sonnet-4.6      [↻]
```

- Each chip is green/amber/red. `~/.hermes/config.yaml` + `hermes --version`
  feed it (no heavy subprocess on every paint).
- **Master power button** (left): the user decides whether to use Hermes and
  *when*. The tab boots **powered-off** — nothing runs, no AI calls, no
  embedded processes. Pressing **Encender** arms Mission launch + Admin
  dashboard + Chat; **Apagar** kills the running mission, stops the dashboard
  (`hermes dashboard --stop`) and shuts the chat server down. Implemented in
  Fase A (`HermesStatusStrip.btn_power` → `HermesPanel._apply_power`).

---

## 4. Sub-tab specs

### 4.1 🚀 Misión  *(evolves the current tab)*

```
┌────────────────────────────────────────────┬─────────────────────────┐
│ Brief: [_________________________________]  │   Live preview          │
│        [_________________________________]  │   ┌───────────────────┐ │
│                                              │   │                   │ │
│ Agente:   [ 🛍 Shopify Liquid expert  ▼]     │   │   (QWebEngine)    │ │
│ Stack:    [ shopify-liquid            ▼]     │   │                   │ │
│ Nicho:    [ gym / fitness             ▼]     │   └───────────────────┘ │
│ Variantes:[ 3 ]  Modelo/variante: [auto ▼]   │   ▶ Preview  ⏹  ⟳       │
│ Proveedor:[ codex ▼]  Max QA fixes:[ 3 ]     │                         │
│ ☑ Envato preflight  ☑ Licensing  ☑ UI/UX Pro │                         │
│                                              │                         │
│ [🚀 Lanzar misión]   [⏹ Detener]             │                         │
├──────────────────────────────────────────────────────────────────────┤
│ Fase:  ● Plan → ○ Crear → ○ Build → ○ QA → ○ Empaquetar                 │
│ ┌─ log ──────────────────────────────────────────────────────────────┐│
│ │ …                                                                   ││
│ └─────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

Changes vs today:
- **Agente** dropdown = list of installed `pcreative-studio-*` specialist skills
  (§5) + an "Auto (Hermes elige)" option. Selecting one passes
  `-s <skill>` to Hermes and pre-selects its default stack.
- **Stack** dropdown = the 77 stacks (grouped by category as in the
  picker). Constrains the mission; "auto" lets `suggest_stack` decide.
- **Nicho** combo (free text + suggestions) → `niche` to `create_project`.
- **Proveedor** = the real 7 from `ai_providers.py`, default = active one.
- **Modelo/variante** = per-variant model override (feeds kanban swarm
  `--model`); "auto" spreads variants across distinct models for diversity.
- **Max QA fixes** spinbox + **Envato preflight / Licensing / UI/UX Pro**
  checkboxes → become explicit flags in the generated prompt instead of
  hardcoded text.
- **Phase indicator** (Plan→Crear→Build→QA→Empaquetar) driven by parsing
  Hermes stdout for known markers (reuse `stream_parsers.py` pattern).
- ≥2 variants → mission uses **kanban swarm** under the hood (§7).

### 4.2 🤖 Agentes — gallery of specialists

Card grid. Each card = one installed `pcreative-studio-*` skill:

```
┌──────────────────────────┐  ┌──────────────────────────┐
│ 🛍  Shopify Liquid        │  │ 📝  WordPress Block       │
│ OS 2.0 · Theme Store      │  │ FSE · theme.json · ACF    │
│ stacks: shopify-liquid,…  │  │ stacks: wordpress-block   │
│ v1.0 · ✓ enabled          │  │ v1.0 · ✓ enabled          │
│ [Usar] [Editar] [Memoria] │  │ [Usar] [Editar] [Memoria] │
└──────────────────────────┘  └──────────────────────────┘
```

- Reads `~/.hermes/skills/pcreative-studio/*/SKILL.md`, parses frontmatter
  (`name`, `description`, `metadata.hermes.tags`, `version`, mapped
  stacks).
- **Usar** → jumps to 🚀 Misión with that agent + its default stack.
- **Editar** → opens the SKILL.md in an editor pane (textarea +
  "Guardar" → writes file → `hermes skills audit` to reload).
- **Memoria** → jumps to 🧠 with this agent's learnings filtered.
- Toggle enable/disable → `hermes skills config`.
- "➕ Nuevo agente" card → 4.3.

### 4.3 ➕ Crear agente

Guided form that writes a valid Hermes SKILL.md:

```
Nombre del agente:   [ Webflow-style landing expert        ]
Slug (auto):         pcreative-studio-webflow-style-landing
Stack(s) base:       [✓ astro-tailwind] [✓ nextjs-shadcn] […]
Tags:                [ landing, marketing, hero, conversion ]
Nicho objetivo:      [ SaaS / startups                      ]
Especialidad (qué sabe / cómo trabaja):
  [ multi-line… reglas, do/don't, secciones típicas,        ]
  [ paletas, performance budget, marketplace target…        ]

[🤖 Generar con IA]   ← Hermes redacta el cuerpo a partir de lo anterior
                         + el contexto del/los stack(s) elegidos

[Vista previa SKILL.md]  [💾 Crear agente]
```

- **💾 Crear agente** → writes
  `~/.hermes/skills/pcreative-studio/<slug>/SKILL.md` with proper frontmatter
  (`name`, `description`, `version: 1.0.0`, `platforms`,
  `metadata.hermes.tags`, `related_skills: [pcreative-studio-operator,
  popular-web-designs, claude-design]`) → `hermes skills audit` → appears
  in 🤖 Agentes.
- **🤖 Generar con IA** → calls the MCP tool `draft_specialist_skill`
  (§6) which runs Hermes/agent to write the body, seeded with the
  stack's `_BUILDER_CONTEXT` block(s).
- Mapping skill→stack stored in the skill frontmatter
  (`metadata.pcreative_studio.stacks: [...]`) — that's how 🚀 Misión and the
  gallery know which stacks a specialist covers.

### 4.4 🧠 Memoria — what Hermes learned

Two columns:
- **Global memories** — browse `~/.hermes/memories/` (read + light edit).
- **Per-project learnings** — for each gallery project, show its
  `.hermes.md` / `AGENTS.md` (what the agent recorded it did + lessons).

Actions: search, open, edit, "olvidar" (delete a memory). A banner
explains the learning loop ("cada misión añade aquí lo que funcionó").

### 4.5 📊 Kanban — swarm missions in flight

Wraps `hermes kanban` on a dedicated board `pcreative-studio`:
- `hermes kanban list --board pcreative-studio` → table (task, assignee,
  status, model, worktree).
- `hermes kanban show <id>` → detail + comments + events.
- Live tail via `hermes kanban tail`.
- This is where a multi-variant mission's workers/verifier/synthesizer
  show up. Read-only v1 (launch happens from 🚀 Misión).

### 4.6 ⏰ Cron — scheduled missions

Wraps `hermes cron`:
- List jobs (`hermes cron list`) with pause/resume/run/remove buttons.
- "➕ Programar misión" → schedule expr (`every Mon 9am`, `0 9 * * 1-5`,
  …) + a mission brief + delivery channel (telegram/discord/email/…).
  Writes via `hermes cron create "<expr>" "<prompt>" --skill <agent>`.
- Use case: *"cada lunes genera una landing nueva del nicho top de la
  semana y mándame el zip por Telegram."*

### 4.7 ⚙️ Admin — embed the native Hermes dashboard

- On open: spawn `hermes dashboard --tui --no-open --host 127.0.0.1
  --port <free>` as a `QProcess`, then load it in a `QWebEngineView`.
- Gives us, for free: Status (sessions/health), Config (schema-driven
  editor), Env (API keys), and an embedded Chat tab.
- On tab close / app exit: `hermes dashboard --stop`.
- This is the "OpenClaw-style admin panel" the user asked about — it
  already exists in Hermes; we just host it.

### 4.8 💬 Chat — interactive Hermes  *(keep current `HermesTerminal`)*

- Already works: embedded xterm running `hermes -s pcreative-studio-operator`.
- Improve: a dropdown to pick which specialist skill the chat loads
  (`-s <skill>`), and auto-follow the project built by the last mission.

---

## 5. Specialist agents (the `pcreative-studio-*` skills)

One Hermes skill per stack family. Each is a `SKILL.md` whose body is the
deep stack knowledge (much of it lifted from the `_*_BUILDER_CONTEXT`
blocks we already wrote in `pcreative_studio.py`).

Proposed initial set (maps onto the 77 stacks / 16 categories):

| Skill slug | Covers stacks | Knowledge source |
|---|---|---|
| `pcreative-studio-operator` | (orchestrator, all) | exists — rewrite delegate→swarm |
| `pcreative-studio-shopify-liquid` | shopify-liquid, shopify-liquid-blank | `_SHOPIFY_BUILDER_CONTEXT` (Liquid 28 KB) |
| `pcreative-studio-shopify-hydrogen` | shopify-hydrogen | Hydrogen block |
| `pcreative-studio-shopify-app` | shopify-polaris-app, shopify-checkout-extension | Polaris block |
| `pcreative-studio-shopify-functions` | shopify-functions | Functions block |
| `pcreative-studio-shopify-webcomponents` | shopify-storefront-webcomponents | WC block |
| `pcreative-studio-wordpress` | wordpress-block, -plugin | WORDPRESS.md |
| `pcreative-studio-wordpress-builders` | -bricks, -elementor, -divi, -breakdance | builder packs |
| `pcreative-studio-magento-hyva` | magento-hyva | Hyvä + Freento MCP |
| `pcreative-studio-saleor` | saleor-nextjs | BSD-3 GraphQL |
| `pcreative-studio-vendure` | vendure | NestJS |
| `pcreative-studio-bigcommerce` | bigcommerce-stencil | Stencil/Cornerstone |
| `pcreative-studio-prestashop` | prestashop-theme | Smarty |
| `pcreative-studio-opencart` | opencart-theme | OC4 Twig |
| `pcreative-studio-sylius` | sylius | Symfony 7 |
| `pcreative-studio-medusa` | medusa | Medusa 2 |
| `pcreative-studio-frontend` | nextjs-*, astro-*, react-*, vue-*, svelte… | generic web-design |
| `pcreative-studio-mobile` | expo-*, flutter, ionic, kotlin-compose | mobile |
| `pcreative-studio-backend` | hono, nestjs, fastapi, go-fiber, … | API design |
| `pcreative-studio-docs` | docusaurus, vitepress, starlight | docs sites |
| `pcreative-studio-game` | phaser, pixijs, r3f | web games |

> We don't have to ship all at once. **Phase A** = orchestrator rewrite +
> 5–6 highest-value specialists (shopify-liquid, hydrogen, wordpress,
> magento-hyva, frontend, mobile). Rest added incrementally + via the
> user's own "Crear agente" form.

### SKILL.md shape (canonical)

```markdown
---
name: pcreative-studio-shopify-liquid
description: "Build Shopify Online Store 2.0 themes to Theme Store / ThemeForest quality via the pcreative-studio MCP."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [pcreative-studio, shopify, liquid, theme-store, envato]
    related_skills: [pcreative-studio-operator, popular-web-designs, claude-design, dogfood]
  pcreative-studio:
    stacks: [shopify-liquid, shopify-liquid-blank]
    default_stack: shopify-liquid
    marketplace: [theme-store, themeforest]
---

# Shopify Liquid specialist
## When to use
## Stack rules (OS 2.0, theme.liquid, Section Rendering API, …)
## Performance budget (Lighthouse 60+ / A11y 90+ / JS ≤16 KB)
## Workflow (create_project → run_agent_build → run_preflight loop → build_zip)
## Pitfalls
## Verification (Theme Check, Lighthouse CI)
```

The `metadata.pcreative_studio.stacks` key is **our** extension — it's how the
GUI maps specialists ↔ stacks. Hermes ignores unknown metadata.

### Bundle
`~/.hermes/skill-bundles/pcreative_studio.yaml`:
```yaml
name: pcreative-studio
description: "Full Pcreative Studio web-design workflow."
skills: [pcreative-studio-operator, popular-web-designs, claude-design, dogfood]
instruction: "You are building marketplace-ready templates with Pcreative Studio. Use the pcreative-studio MCP tools."
```
`/pcreative-studio` in any Hermes chat loads the whole workflow at once.

---

## 6. New MCP tools (in `mcp_server.py`)

So Hermes can *operate* Pcreative Studio fully (not just read):

| Tool | Signature | Wraps |
|---|---|---|
| `apply_theme` | `(project_path, theme_key)` | the theme/token system |
| `setup_licensing` | `(project_path, stack_family)` | `licensing_scaffold` |
| `analyze_market` | `(niche?, year?)` | `market_analyzer` |
| `list_pcreative_studio_skills` | `()` → specialists + their stacks | scans skills dir |
| `register_custom_skill` | `(name, body, stacks, tags)` | writes SKILL.md + audit |
| `draft_specialist_skill` | `(name, stacks, niche, notes)` → SKILL body | seeds from `_BUILDER_CONTEXT` |
| `learn_from_project` | `(project_path, lesson)` | append to `.hermes.md` |
| `list_mcp_catalog` | `(stack?)` → relevant MCPs | `mcp_catalog.py` |

All writes stay **local** (user's machine); nothing here touches the
public GitHub repo or the pcreative backend.

---

## 7. Parallel variants via Kanban Swarm  (closes Fase #19)

Replace the fictional `delegate_task` with the real native flow. For an
N-variant mission, the orchestrator skill does:

```
hermes kanban swarm \
  --board pcreative-studio \
  --workers N \
  --task "Build variant {i}: <brief> with DISTINCT UI/UX Pro style+palette" \
  --model-per-worker auto         # variant A=sonnet, B=gpt-5, C=gemini…
  --worktree                      # isolation per worker
  --verifier "run_preflight; fix ≤max_qa_fixes; must pass Envato checklist" \
  --synthesizer "pick best; report path/style/QA/zip per variant"
```

- Workers build in parallel, each in its own git worktree (no clobber).
- Verifier node runs `run_preflight` (+ Envato checklist) and loops fixes.
- Synthesizer compares and reports.
- The 📊 Kanban sub-tab visualizes this in real time.

**Envato QA loop:** the verifier prompt embeds the ThemeForest hard-reject
checklist (responsive, no console errors, documentation present, licensed
assets, performance). `run_preflight` already covers part of it; we extend
its checks to match Envato's reviewer rubric.

---

## 8. Scheduled missions via Cron  (closes Fase #21, partial)

The ⏰ Cron sub-tab wraps `hermes cron`. No scheduler code of our own.
Sandbox/remote bits of old Fase #21 remain out of scope for now (Hermes
`terminal.backend: docker` already offers sandboxing if we want it later).

---

## 9. Phased execution plan

| Phase | Deliverable | Touches | Risk |
|---|---|---|---|
| **0 ✅** | `hermes update` to v0.15.0; verified swarm/cron/dashboard CLIs | env only | low |
| **A ✅** | Renamed Operator→Hermes; 8-sub-tab shell; status strip + **master power button** (boots off); embedded Admin dashboard; Misión (with phase indicator) + Chat working | `hermes_panel.py` (new), `operator_panel.py` (+shutdown/relaunch), `pcreative_studio.py` (tab+gallery btn), docs | low |
| **B** | 🤖 Agentes gallery + 6 starter `pcreative-studio-*` skills + bundle | new skills, gallery widget | med |
| **C** | Misión upgrades: agent/stack/provider/model/QA controls + phase indicator | `hermes_panel.py`, `stream_parsers.py` | med |
| **D** | New MCP tools (§6) | `mcp_server.py` | med |
| **E** | ➕ Crear agente (form + AI draft) | gallery + tool `draft_specialist_skill` | med |
| **F** | 📊 Kanban swarm wiring (rewrite orchestrator skill) — Fase #19 | SKILL.md, kanban wrap | high |
| **G** | ⏰ Cron sub-tab — Fase #21 | cron wrap | low |
| **H** | 🧠 Memoria browser | memories/.hermes.md viewer | low |
| **I** | Docs: HERMES.md user guide + USER_GUIDE §, CHANGELOG | docs | low |

Each phase is independently shippable and leaves the tab working.

---

## 10. Constraints & decisions carried in

- **Provider parity:** every AI feature must work across all 7 providers,
  no half-implementation (see memory `feedback-full-provider-parity`).
- **Active-provider only:** when writing a project context file, write the
  active provider's file only (CLAUDE.md *or* AGENTS.md *or* GEMINI.md),
  not all three (memory `nono solo el modelo que este activo`).
- **Local vs public:** all Hermes/skill/MCP/licensing wiring is **local**
  to the user's machine. The public GitHub repo ships only placeholders;
  the pcreative backend is never referenced in committed code.
- **Hermes is optional:** the rest of Pcreative Studio must keep working with
  Hermes absent — every Hermes feature degrades to an "install Hermes"
  hint, exactly as today.
- **Don't reimplement Hermes:** wrap/embed swarm, cron, dashboard, skills.
- **Ask before design/UX/palette/copy decisions** (memory
  `feedback-ask-before-design-decisions`).

---

## 11. Open questions for the user

1. **Tab scope:** keep all 8 sub-tabs, or trim (e.g. drop Kanban/Cron for
   v1 and add later)?
2. **Specialist set:** start with the 6 in Phase B, or a different 6?
3. **Naming:** "Hermes" as the tab label, or "Hermes (Agentes)" /
   "Agentes IA" to make the purpose obvious to a buyer who's never heard
   of Hermes?
4. **AI draft of skills:** which provider should `draft_specialist_skill`
   use by default — the active one, or always a strong model (e.g. Opus
   via OpenRouter)?
5. **Cron delivery:** do you want Telegram/Discord delivery wired, or just
   "save zip to disk" for v1?
