# NOTICE — third-party software

ThemeForge ships under **GPL v3** (see `LICENSE`). It depends on,
embeds, or invokes the following third-party components. This NOTICE
file aggregates their licenses and attribution requirements for the
convenience of distributors and users.

## Embedded (shipped as part of this repo or auto-installed)

### Embedded terminal — `terminal/`

These are listed as dependencies in `terminal/package.json` and are
installed under `terminal/node_modules/` when you run `npm install`:

| Package | License | Project URL |
|---|---|---|
| `@xterm/xterm` | MIT | <https://xtermjs.org/> |
| `@xterm/addon-fit` | MIT | <https://xtermjs.org/> |
| `node-pty` | MIT | <https://github.com/microsoft/node-pty> |
| `ws` | MIT | <https://github.com/websockets/ws> |

The MIT license is included in each package's `LICENSE` file under
`terminal/node_modules/<package>/LICENSE`.

### Pixel Office visualizer

ThemeForge auto-installs (with user consent) a Node application that
shows AI agent sessions as pixel-art avatars on a virtual office. The
visualizer is fetched from:

- **Upstream**: <https://github.com/neomatrix25/pixel-office-openclaw>
  — by **neomatrix25**, MIT.
- **Fork used by ThemeForge**:
  <https://github.com/pcreativedev/pixel-office-openclaw> — same code +
  two commits adding a Claude Code session reader and same-origin
  auto-connect. Also MIT.

Neither the upstream nor the fork is bundled in this repository. They
are cloned at install time into
`~/.local/share/themeforge/pixel-office-openclaw/` from the user's
machine.

## Invoked as external subprocesses (NOT bundled)

ThemeForge does not bundle these tools; it only spawns them as child
processes when the user selects the corresponding provider. The user
is expected to install them through their distro's package manager or
each project's official channel.

| Tool | License | Project URL | Used as |
|---|---|---|---|
| Claude Code CLI (Anthropic) | Apache 2.0 | <https://github.com/anthropics/claude-code> | AI agent (`claude`) |
| Codex CLI (OpenAI) | Apache 2.0 | <https://github.com/openai/codex> | AI agent (`codex`) |
| Gemini CLI (Google) | Apache 2.0 | <https://github.com/google-gemini/gemini-cli> | AI agent (`gemini`) |
| OpenCode CLI | MIT | <https://github.com/sst/opencode> | AI agent (`opencode`, npm pkg `opencode-ai`) |
| UI UX Pro Max | MIT | <https://github.com/nextlevelbuilder/ui-ux-pro-max-skill> | Optional design skill (`uipro-cli init --ai <agent>`) for 161 reasoning rules + 67 UI styles + 161 paletas. Invoked when the "uipro" checkbox is enabled in the project form. |
| **Lucide icons** | ISC | <https://github.com/lucide-icons/lucide> | 38 SVG icons bundled in `assets/icons/lucide/` and used for the main-window tabs and Settings widgets. SVGs use `currentColor` so they re-tint to the active theme's accent. ISC is functionally equivalent to MIT — full attribution preserved in the SVG files. |
| W3C DTCG spec | (community) | <https://www.designtokens.org/tr/drafts/format/> | Theme JSON format reference for the Figma import path. ThemeForge parses tokens following the DTCG v2025.10 spec (`$type` + `$value` with `$`-prefixed metadata). |
| Tokens Studio for Figma | (referenced, not bundled) | <https://docs.tokens.studio/> | Recommended Figma plugin for exporting design tokens as DTCG JSON to feed ThemeForge's Figma import dialog. Not redistributed. |
| GitHub CLI (`gh`) | MIT | <https://github.com/cli/cli> | Repo create / push from the ProjectWindow |
| `paru` | GPL v3 | <https://github.com/Morganamilo/paru> | AUR helper hint in docs |

## Referenced by name (NOT redistributed)

When the `autoskills` checkbox is enabled and the AI provider supports
it (Claude or Codex), ThemeForge invokes `npx --yes autoskills -a
<provider>`, which in turn fetches the following skill packages by
name. ThemeForge does NOT bundle, redistribute, or modify these
packages.

| Skill package | Owner |
|---|---|
| `anthropics/skills/frontend-design` | Anthropic |
| `vercel/skills/nextjs-best-practices` | Vercel |
| `wordpress/skills/block-theme-development` | WordPress |
| `shopify/skills/theme-development` | Shopify |

Each skill package is governed by its own license; see the respective
repository for terms.

## ⚠️ autoskills (midudev) — CC BY-NC 4.0

[`autoskills`](https://github.com/midudev/autoskills) by **midudev** is
the tool ThemeForge invokes (via `npx`) to install the skill packages
listed above. It is licensed under **Creative Commons
Attribution-NonCommercial 4.0** (CC BY-NC 4.0).

Implications:

- ✅ Distributing ThemeForge for free under GPL v3 with autoskills as
  an optional dependency is consistent with the autoskills license.
- ⚠️ Selling ThemeForge or shipping it as part of a commercial product
  with the autoskills checkbox enabled by default is a grey area
  under CC BY-NC 4.0. Maintainers of downstream commercial builds
  should either:
  - keep the checkbox OFF by default and document the user opt-in,
  - obtain explicit permission from midudev, or
  - replace autoskills with a permissive alternative.

Attribution to midudev is preserved in:

- `themeforge.py` (tooltip of the autoskills checkbox).
- `docs/USER_GUIDE.md` (§17, "Credits and third-party licenses").
- This NOTICE file.

## Foundational dependencies

| Component | License | Why it matters |
|---|---|---|
| **PyQt6** (Riverbank) | GPL v3 or commercial | Forces ThemeForge as a whole to be distributed under GPL v3 (the LICENSE in this repo). |
| **CPython** ≥ 3.11 | PSF | Runtime. |
| **Qt 6** (The Qt Company) | LGPL v3 / commercial | Under the hood of PyQt6. |
| **Node.js** ≥ 20 | MIT | Runtime for the embedded terminal server and the scaffolding commands of most stacks. |

## Reporting an attribution error

If anything in this file is incorrect, outdated, or missing,
please open an issue against the repository.
