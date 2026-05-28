"""
market_analyzer — análisis de mercado de productos digitales con IA.

Llama directamente al endpoint HTTPS de OpenRouter (sin CLI) usando la
``OPENROUTER_API_KEY`` que el usuario ya tiene configurada en credenciales
(ver ``ai_providers.get_env('openrouter')``).

Tipos de análisis:
  - general:     mercado completo 2026 (best-sellers, stacks, gaps, tendencias).
  - niche:       deep-dive en UN nicho concreto.
  - compare:     comparativa de DOS nichos.
  - marketplace: análisis de UN marketplace (ThemeForest, Gumroad, etc.).
  - prediction:  proyección 2026 → 2027.

El histórico vive en ``~/.config/themeforge/market_analyses/`` (gitignored).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "themeforge"
ANALYSES_DIR = CONFIG_DIR / "market_analyses"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODEL = "google/gemini-2.5-pro"

# Modelos preseleccionados en el picker (todos vía OpenRouter).
MODELS = [
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "anthropic/claude-opus-4.7",
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-5",
    "openai/gpt-5-thinking",
    "x-ai/grok-4",
    "deepseek/deepseek-v3.1",
]

# Marketplaces para el botón «Por marketplace».
MARKETPLACES = [
    "ThemeForest (Envato)",
    "CodeCanyon (Envato)",
    "Gumroad",
    "Lemon Squeezy",
    "Creative Market",
    "Itch.io (games + assets)",
    "ArtStation (3D + game assets)",
    "GitHub Sponsors / OSS",
    "Shopify Theme Store",
    "WordPress.org (themes/plugins)",
]


# ─── Prompts ────────────────────────────────────────────────────────────


_SYSTEM = (
    "Eres un analista senior del mercado de productos digitales para "
    "desarrolladores y creators. Conoces a fondo ThemeForest, CodeCanyon, "
    "Gumroad, Lemon Squeezy, Creative Market, Itch.io, ArtStation, GitHub "
    "Sponsors, Shopify Theme Store y wp.org. Das datos concretos (cifras "
    "estimadas, rangos de precio, % de cuota, tendencias). NO te quedas en "
    "generalidades. Output en MARKDOWN bien estructurado, con tablas donde "
    "tenga sentido. Idioma: español neutro."
)


def prompt_general() -> str:
    return """# Análisis exhaustivo del mercado de productos digitales — 2026

Cubre con datos concretos los principales marketplaces: ThemeForest, CodeCanyon, Gumroad, Lemon Squeezy, Creative Market, Itch.io, ArtStation, GitHub Sponsors/OSS, Shopify Theme Store, WordPress.org.

Para cada uno, dame:

## 1. Top 10 nichos más vendidos en 2026
Tabla con columnas: nicho · marketplace dominante · volumen mensual estimado (#ventas y/o $) · rango de precio · tendencia (📈/➡️/📉) · saturación (1-10).

## 2. Sub-nichos emergentes (creciendo en 2026)
Incluye específicamente — pero no limitado a:
- **Gaming**: indie devs, mobile games, esports infra, streamers, asset shops, game studios, tournament platforms, browser games.
- **AI/LLM**: agentes, MCP servers, plugins de IA para WP/Shopify, AI image/video tooling.
- **Web3/crypto** maduro.
- **Health/wellness** (coaching, nutrición, mental health).
- **No-code/low-code** templates.
- **Creator economy** (cursos, membresías, newsletters).

## 3. Stack tecnológico ganador POR nicho
Para CADA nicho top, lista los stacks que están vendiendo MÁS. MÍNIMO 5-7 stacks por nicho — no te quedes solo en Next.js y Astro. Incluye:
- Frontend: Next.js, Astro, Nuxt, SvelteKit, Remix, Vite+Vue, Vite+React, Webflow-export.
- WordPress: FSE puro, Bricks, Elementor, Divi, Breakdance, classic+ACF.
- Mobile: Expo/React Native, Flutter, Kotlin Compose, SwiftUI.
- Backend/full-stack: Laravel+Inertia, NestJS+Prisma, FastAPI, Django, t3-stack, RedwoodJS.
- Shopify themes (Liquid + Hydrogen).
- Game engines / tooling: Godot, Unity asset bundles.

## 4. Tendencias generales 2026
- **Builders WP**: Bricks vs Elementor vs FSE — quién lidera vs quién pierde cuota.
- **Mobile**: Expo vs Flutter vs Kotlin Compose adoption.
- **Backend**: Laravel/Nest/FastAPI/Django adoption.
- **AI/LLM products**: agentes, MCP servers, plugins de IA — el boom real.
- **Performance**: Core Web Vitals como diferenciador comercial.
- **Pricing power**: precios subiendo / bajando por categoría.

## 5. Gap analysis — nichos BAJO-servidos
Lista 8-12 combinaciones (nicho × stack × marketplace) con: ALTA demanda + BAJA competencia. Donde hay oportunidad real para entrar nuevo.

## 6. Predicciones 2026 → 2027
- Qué nichos van a explotar.
- Qué stacks van a perder relevancia.
- Qué tipo de producto deberíamos lanzar HOY si queremos cobrar el próximo año.

Sé concreto con cifras estimadas. Si no tienes datos exactos, da rangos razonables y di "estimado". El output debe servirme para decidir QUÉ crear esta semana."""


def prompt_niche(niche: str) -> str:
    return f"""# Deep-dive de mercado — nicho: «{niche}» (2026)

Analiza este nicho específico en profundidad. Dame:

1. **Tamaño y volumen**: ¿cuánto se mueve aquí? Marketplaces principales y ventas mensuales estimadas.
2. **Top 10 productos vendidos** en 2026 (nombre / autor si lo recuerdas / precio / ventas / por qué venden).
3. **Stacks tecnológicos más vendidos** para este nicho — MÍNIMO 7 opciones distintas con pros/contras comerciales (no técnicos).
4. **Sub-nichos calientes** dentro de este vertical.
5. **Tendencias 2026**: qué pide la gente, qué se queda anticuado.
6. **Pricing strategy**: rangos de precio, qué justifica precios premium ($79-149), qué se vende mejor en bajo precio ($19-39).
7. **Marketing / SEO hooks** que están funcionando este año en este nicho.
8. **Competidores top a estudiar** (3-5 nombres concretos) y qué hace cada uno bien/mal.
9. **Gap analysis**: ángulos infraexplotados — dónde entrar a competir con ventaja.
10. **Plan de ataque para 2026**: si lanzara un producto hoy en este nicho, ¿qué exactamente debería sacar (formato, stack, precio, USP)?

Markdown bien estructurado, tablas donde aporte."""


def prompt_compare(niche_a: str, niche_b: str) -> str:
    return f"""# Comparativa de mercado: «{niche_a}» vs «{niche_b}» (2026)

Comparativa lado a lado de ambos nichos para decidir cuál atacar.

## Tabla comparativa
| Métrica | {niche_a} | {niche_b} |
|---|---|---|
| Volumen mensual de ventas | … | … |
| Precio medio | … | … |
| Saturación (1-10) | … | … |
| Tendencia 2026 | … | … |
| ROI tiempo→ventas | … | … |
| Marketplace dominante | … | … |
| Stacks top (3) | … | … |
| Esfuerzo de creación (h) | … | … |

## Análisis cualitativo
- ¿Quién paga mejor en cada nicho?
- ¿Cuál crece más rápido?
- ¿Cuál tiene mayor lifetime value (upsells, updates)?
- ¿Cuál es más resistente a cambios de marketplace algorithm?

## Recomendación
Sé claro: si tuvieras que elegir UNO de los dos para lanzar en 30 días con presupuesto limitado, ¿cuál y por qué? Justifica con datos."""


def prompt_marketplace(marketplace: str) -> str:
    return f"""# Análisis profundo de marketplace — «{marketplace}» (2026)

Concéntrate solo en este marketplace.

1. **Salud del marketplace en 2026**: tráfico, ventas totales aproximadas, crecimiento YoY.
2. **Categorías más vendidas** este año (top 10) con cuota y precio medio.
3. **Top sellers/items 2026** (con cifras estimadas).
4. **Algorithm/discoverability**: cómo se posiciona arriba en 2026 (SEO interno, ratings, refreshes, tags…).
5. **Pricing tiers que más venden** y por qué.
6. **Requisitos de calidad/aprobación** (si aplica).
7. **Comisiones / split** vigente.
8. **Tendencias que premian** vs lo que castiga el algoritmo.
9. **Tipos de producto infraexplotados** con potencial alto.
10. **Estrategia ganadora** para entrar nuevo en este marketplace en 2026: primeros 90 días, qué publicar, cómo escalar.

Markdown con tablas."""


def prompt_prediction() -> str:
    return """# Predicción de mercado 2027 — productos digitales

Mira a 12 meses vista. Argumenta con datos y tendencias actuales (2026).

## 1. Nichos que van a EXPLOTAR en 2027
Top 10, con justificación de por qué crecerán.

## 2. Nichos que van a DECRECER
Top 8, con qué los está canibalizando.

## 3. Stacks ganadores en 2027
- Frontend / WP / mobile / backend / AI tooling.
- Qué va a desplazar a los líderes actuales.

## 4. Tipos de producto nuevos que aparecerán
- Categorías que hoy no existen como tal y que serán mainstream en 2027.

## 5. Riesgos de mercado
- Marketplaces que podrían perder cuota.
- Cambios algorítmicos que castigarán a quién.
- Saturación inminente.

## 6. Plan de inversión de tiempo (mío) para 2026-2027
Si tuviera que dedicar mis próximos 6 meses a crear productos digitales que se vendan en 2027, ¿exactamente qué crearía? Lista priorizada con esfuerzo estimado y revenue esperado por ítem.

Markdown bien estructurado, sé concreto."""


# ─── Engine ─────────────────────────────────────────────────────────────


@dataclass
class AnalysisRequest:
    kind: str           # general | niche | compare | marketplace | prediction
    params: dict        # {niche: ...} | {a:..., b:...} | {marketplace:...}
    model: str          # ID OpenRouter
    user_prompt: str    # ya renderizado


def build_request(kind: str, model: str, params: dict | None = None) -> AnalysisRequest:
    params = params or {}
    if kind == "general":
        p = prompt_general()
    elif kind == "niche":
        p = prompt_niche(params.get("niche", ""))
    elif kind == "compare":
        p = prompt_compare(params.get("a", ""), params.get("b", ""))
    elif kind == "marketplace":
        p = prompt_marketplace(params.get("marketplace", ""))
    elif kind == "prediction":
        p = prompt_prediction()
    else:
        raise ValueError(f"kind desconocido: {kind}")
    return AnalysisRequest(kind=kind, params=params, model=model, user_prompt=p)


def call_openrouter(req: AnalysisRequest, api_key: str, timeout: int = 240) -> str:
    """Llama a OpenRouter chat/completions con el prompt y devuelve el
    contenido del mensaje. Lanza RuntimeError con mensaje legible si falla."""
    if not api_key:
        raise RuntimeError("Falta OPENROUTER_API_KEY (configura la credencial de OpenRouter en Settings).")

    body = {
        "model": req.model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": req.user_prompt},
        ],
        "temperature": 0.4,
    }
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter recomienda estos headers para aparecer en su leaderboard.
        "HTTP-Referer": "https://github.com/pcreativedev/themeforge",
        "X-Title": "ThemeForge - Market Analyzer",
    }
    request = urllib.request.Request(OPENROUTER_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
            raise RuntimeError(f"OpenRouter {e.code}: {err.get('error', {}).get('message') or err}")
        except Exception:
            raise RuntimeError(f"OpenRouter HTTP {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Sin conexión a OpenRouter: {e.reason}")
    try:
        return payload["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"Respuesta inesperada de OpenRouter: {str(payload)[:300]}")


# ─── Histórico ──────────────────────────────────────────────────────────


def _ensure_dir() -> None:
    ANALYSES_DIR.mkdir(parents=True, exist_ok=True)


def save_analysis(req: AnalysisRequest, content: str) -> Path:
    _ensure_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug = req.kind
    if req.kind == "niche":
        slug = f"niche-{_slugify(req.params.get('niche',''))}"
    elif req.kind == "compare":
        slug = f"compare-{_slugify(req.params.get('a',''))}-vs-{_slugify(req.params.get('b',''))}"
    elif req.kind == "marketplace":
        slug = f"marketplace-{_slugify(req.params.get('marketplace',''))}"
    fn = ANALYSES_DIR / f"{ts}__{slug}.md"
    header = (
        f"<!-- themeforge-market-analyzer\n"
        f"kind: {req.kind}\n"
        f"params: {json.dumps(req.params, ensure_ascii=False)}\n"
        f"model: {req.model}\n"
        f"date:  {datetime.now().isoformat(timespec='seconds')}\n"
        f"-->\n\n"
    )
    fn.write_text(header + content, encoding="utf-8")
    return fn


def _slugify(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return ("".join(out)).strip("-")[:40] or "x"


def list_analyses() -> list[Path]:
    _ensure_dir()
    return sorted(ANALYSES_DIR.glob("*.md"), reverse=True)


def load_analysis(p: Path) -> tuple[dict, str]:
    """Devuelve (metadata, contenido). metadata lleva kind/params/model/date."""
    txt = p.read_text(encoding="utf-8")
    meta: dict = {}
    body = txt
    if txt.startswith("<!-- themeforge-market-analyzer"):
        try:
            end = txt.index("-->")
            head = txt[:end]
            body = txt[end + 3:].lstrip("\n")
            for line in head.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
        except Exception:
            pass
    return meta, body


# ─── Util para resolver la API key ──────────────────────────────────────


def get_openrouter_key() -> str:
    """Obtiene la key de OPENROUTER. Primero ai_providers.get_env, luego
    ENV directo, luego ~/.config/themeforge/credentials.json si existiera."""
    try:
        import ai_providers as aip
        env = aip.get_env("openrouter") or {}
        if env.get("OPENROUTER_API_KEY"):
            return env["OPENROUTER_API_KEY"]
    except Exception:
        pass
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    return ""
