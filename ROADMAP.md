# Roadmap — ThemeForge

Future improvements organised by feature area. Items here are not
scheduled — they represent known gaps and ideas to revisit.

For pre-publication blockers (private to the maintainer), see
`ANTES-DE-PUBLICAR.md` (gitignored).

---

## 🚀 Demo deploy

Current state: deploys static / SPA stacks to Netlify / Vercel /
Cloudflare Pages / Surge with auto-detected build command + dist dir.
See `docs/USER_GUIDE.md` §10 for full details.

### Future updates

- **Server-rendered support.** Add a "Server" deploy path for stacks
  that need a runtime (Laravel, WordPress, Express, Rails, Spring,
  Phoenix…). Candidate targets:
  - Render (`render.yaml` + Git push)
  - Railway (`railway up`)
  - Fly.io (`fly deploy`)
  - DigitalOcean App Platform (spec yaml)
  - VPS via SSH/rsync (manual config)
- **Custom domain configuration.** After deploy, prompt to alias the
  generated `*.netlify.app` / `*.vercel.app` to a user-owned domain.
  Per provider:
  - Netlify: `netlify sites:update --custom-domain`
  - Vercel: `vercel domains add`
  - Cloudflare Pages: API call to attach custom domain
  - Surge: deploy directly to `<chosen>.example.com` if CNAME exists
- **Deploy history per project.** Persist every deploy (timestamp,
  provider, URL, build duration, dist size) in
  `~/.config/themeforge/deploys.json`. Show in a sub-tab of the
  ProjectWindow with rollback links (Netlify/Vercel preserve old
  deploys for free).
- **Multi-provider parallel deploy.** "Deploy to all" button that
  fires Netlify + Vercel + CF Pages simultaneously to compare
  cold-start performance / regional CDN coverage.
- **Pre-deploy lighthouse pass.** Optional checkbox to run
  `lighthouse <deployed-url>` after deploy and surface the score in
  the success popup (perf / a11y / SEO / best-practices).
- **Deploy to PR preview branch.** Detect current git branch; for
  branches != main, deploy to a preview slug
  (`<branch>--<project>.netlify.app`) and post the URL as a GitHub
  comment if a PR exists.
- **Auth-status indicator pre-deploy.** Run `netlify status` /
  `vercel whoami` synchronously before the deploy dialog opens and
  show a green dot / red dot per provider. Skip dropdown providers
  not authed unless user clicks "use anyway".
- **Headless / CI auth via env vars.** Document how to drive the
  deploy from a CI runner via `NETLIFY_AUTH_TOKEN`, `VERCEL_TOKEN`,
  `CLOUDFLARE_API_TOKEN`, `SURGE_LOGIN` + `SURGE_TOKEN`. (Useful for
  ThemeForge running on a build server.)

---

## 💰 AI cost tracker

Current state: scans Claude Code + Codex local stores, renders
QtCharts donut + bar + stacked-bar, with detail tables. Pricing
hard-coded for common models. See §12 of USER_GUIDE.

### Future updates

- **Gemini scanner.** gemini-cli does not currently persist token
  usage locally. Track upstream issue / wait for an API. Fallback:
  link to Google AI Studio billing page.
- **OpenCode scanner.** Same as Gemini — depends on what OpenRouter
  / OpenCode persists locally.
- **Pricing refresh from a remote manifest.** Optional `pricing.json`
  in `~/.config/themeforge/` overrides `cost_tracker.PRICING`. Long
  term, fetch from a community-maintained manifest with consent.
- **Ephemeral 1h cache pricing.** Differentiate 5-min vs 1-hour cache
  rates per Anthropic's tiered cache pricing.
- **Long-context tier pricing** (`[1m]` Opus variants etc.).
- **Cost forecast.** "At this monthly burn rate you'll spend $X by
  EOM" — extrapolate from the current month's average daily cost.
- **Budget alerts.** Soft warning when crossing a configurable
  monthly threshold (e.g. notify when month-to-date > $500).
- **Per-project tagging.** Group projects into "client work" /
  "personal" / "research" buckets and show cost breakdown per bucket.

---

## 📦 Marketplace ZIP builder

Current state: builds a ThemeForest-ready ZIP excluding 30+ noise
patterns, with documentation/screenshots/source opt-ins.

### Future updates

- **Per-marketplace presets.** ThemeForest, CodeCanyon, Gumroad,
  Creative Market each have slightly different layout conventions
  (e.g. ThemeForest requires `Main Files/`, `Documentation/`,
  `Licensing/` subfolders). Add a preset picker that restructures the
  ZIP accordingly.
- **License file injection.** Auto-add `LICENSE.txt` (regular or
  extended depending on marketplace) at the ZIP root, generated from
  a template.
- **Demo-data ZIP variant.** Separate `<slug>-demo-data.zip` with
  WordPress export, Sanity dataset, etc., for buyers to populate
  their copy.

---

## 🔬 Pre-flight checker

Current state: 13 automated checks for marketplace readiness.

### Future updates

- **Customizable check list.** YAML-driven check definitions in
  `~/.config/themeforge/preflight.yaml` so users can disable / add
  custom checks without editing `preflight.py`.
- **Automatic fix suggestions.** For some warns (missing LICENSE,
  missing README, .env tracked) offer a one-click "fix it" action.
- **Lighthouse integration.** Auto-run lighthouse against the local
  preview URL and surface scores in the pre-flight report.
- **HTML validation.** Auto-run html-validate against built output
  and report violations.
- **CSS lint pass.** stylelint pass surfaced in the report.
- **Image weight check.** Flag images > 200 KB unoptimized.

---

## 🖼️ Gallery

Current state: card view with thumbnails, tags, last AI session,
archive toggle.

### Future updates

- **Bulk operations.** Multi-select projects in the gallery and bulk
  archive / tag / delete.
- **Sort options.** Sort by last modified, last AI session, alphabetic,
  cost burned, lines of code.
- **Search by content.** Full-text search across CLAUDE.md /
  AGENTS.md files in project tree (not just project names).
- **Project templates.** Pin certain projects as "template starters"
  for one-click cloning into a new project.

---

## 🧩 Plugin system

Current state: user plugins at `~/.config/themeforge/plugins/*.py`
can register stacks / template types / agents.

### Future updates

- **Hook plugins.** Allow plugins to register lifecycle hooks
  (`on_project_created`, `pre_deploy`, `post_deploy`,
  `before_zip_build`) for advanced customisation.
- **Plugin marketplace.** Optional plugin browser that pulls from a
  community git repo (`themeforge-plugins/awesome-plugins`).
- **Sandboxing.** Currently plugins have full Python access. For
  shared / community plugins, add a permission model (filesystem,
  network, subprocess).
- **Hot-reload.** Watch the plugins dir and reload without restart.

---

## 🤝 Multi-agent compare

Current state: main-window tab that runs the same prompt across
Claude / Codex / Gemini / OpenCode CLIs in parallel, side-by-side
panes with live streaming output, TTFT and wall time per agent. See
§13 of USER_GUIDE.

### Future updates

- **Token / cost extraction.** Parse stream-json from Claude
  (`--output-format stream-json`) and equivalent from Codex to
  extract `input_tokens`, `output_tokens`, model, and compute cost
  via `cost_tracker.PRICING`. Show in pane stats line.
- **Per-agent model picker.** Dropdown per agent to override the
  default model (opus vs sonnet for claude, o3 vs gpt-5-codex-pro
  for codex, etc.).
- **Diff view.** Toggle to show line-by-line diff between two
  agents' outputs (highlights divergences).
- **Vote-merge / cherry-pick.** Select paragraphs from each agent's
  output and assemble a composite response. Output to clipboard or
  inject into a target file.
- **"Use as canonical" action.** Pick the winner and inject its
  response into the project's CLAUDE.md as the canonical answer to
  the prompt.
- **Per-agent system prompt / temperature.** Configure prompt
  variations per agent for A/B testing.
- **Prompt history.** Persist last N prompts in
  `~/.config/themeforge/multi_agent_history.json` for quick recall.
- **Markdown rendering pane toggle.** Toggle between raw text and
  rendered markdown view per pane.
- **Concurrent prompt template variables.** Run the same template
  with different variables (`{name}` → "Alice" / "Bob" / "Carol")
  across one agent to compare outputs.

---

## 🌐 General product

### Future updates

- **i18n.** Currently UI is in Spanish / docs in English. Add a
  language picker (en / es / pt / fr) for the UI.
- **Onboarding tour.** First-launch interactive walkthrough that
  builds a sample project, runs preflight, builds a ZIP.
- **Telemetry (opt-in).** Anonymised usage stats so we can see which
  stacks / providers people actually use.
- **Update notifier.** Check GitHub releases on startup and surface
  available updates in the Settings panel.

---

## 🖥️ Cross-platform support

Current state: officially supported on **Linux** (developed on
CachyOS + KDE Plasma 6 Wayland, tested on Ubuntu / Fedora / Arch
derivatives). PyQt6 itself is cross-platform but ThemeForge has
several Linux assumptions baked in.

### macOS — in progress

MVP port underway. Tracked changes:

- ✅ Cross-platform `platform_compat.py` module with file-manager,
  terminal-launcher, shell-exec and VSCode-launcher helpers.
- ⏳ Replace `bash -lc` with `$SHELL -lc` (zsh on modern macOS).
- ⏳ Replace direct `dolphin`/`xdg-open` calls with
  `platform_compat.open_in_file_manager()`.
- ⏳ Replace Konsole-specific terminal launcher with
  `platform_compat.open_in_terminal()` (Terminal.app on Mac).
- ⏳ Build `.app` bundle with `py2app` (alternative to user running
  `python3 themeforge.py` from terminal).
- ⏳ Use `~/Library/Application Support/themeforge/` instead of
  `~/.config/themeforge/` (or symlink both for backwards compat).
- ⏳ Smoke-test ZIP builder, demo deploy, multi-agent compare on a
  Mac.

### Windows — backlog

Larger porting effort (no native bash). Plan:

- Replace shell-exec invocations with platform dispatch:
  PowerShell on Windows, `bash -lc` on Linux, `zsh -lc` on macOS.
- Replace `xdg-open` with `start` / `explorer.exe`.
- Replace Konsole with Windows Terminal / cmd.exe.
- Path conventions: `%APPDATA%\themeforge\` via
  `QStandardPaths.AppDataLocation`.
- Bundle as `.exe` (`pyinstaller` or `briefcase`).
- Test against PowerShell 7+ as minimum (older versions have
  unicode bugs).
- Decide on AI CLI invocation: claude/codex/gemini/opencode all
  ship cross-platform Node binaries, should JustWork™ once shell
  abstraction is in place.

### Cross-platform infrastructure (apply to all)

- Replace direct `~/.config/themeforge/` references with a
  `app_config_dir()` helper that returns the OS-correct location.
- Replace direct `~/.cache/themeforge/` with `app_cache_dir()`.
- Wrap all `subprocess.run`/`Popen`/`QProcess.start` calls that use
  a shell with a `_run_shell()` helper.
- Test matrix in CI once we have a release: Ubuntu 24, Fedora 40,
  Arch (rolling), macOS 13+, Windows 11.
