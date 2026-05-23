# Requisitos / Checklist ThemeForest (Site Templates)

Este documento es contexto base para cualquier template que vayas a vender en ThemeForest. Léelo antes de empezar y úsalo como criterio de aceptación al terminar.

## Estructura mínima del paquete de entrega

```
template-name/
├── template/              # archivos finales del tema
│   ├── index.html
│   ├── ...
│   ├── assets/
│   └── ...
├── documentation/         # docs HTML estáticas (Envato lo exige)
│   ├── index.html
│   ├── assets/
│   └── ...
├── source/                # ficheros editables (PSD, Figma export, SCSS sin compilar...)
└── licensing.txt
```

## Validaciones automáticas a pasar

- HTML válido (https://validator.w3.org) — sin errores.
- CSS válido (jigsaw.w3.org/css-validator).
- Lighthouse: Performance ≥ 90, SEO ≥ 95, Accessibility ≥ 90, Best Practices ≥ 95.
- Sin enlaces rotos (`linkchecker` o `htmltest`).
- Responsive: 360, 768, 1024, 1280, 1440, 1920px.

## Reglas no negociables Envato

1. **Sin frameworks abandonados**: no jQuery legacy salvo que sea estrictamente necesario para un plugin. Bootstrap 5+, no 3.
2. **Vanilla JS o framework moderno**: nada de IE shims, polyfills inútiles.
3. **Originalidad de assets**: imágenes con licencia (Unsplash/Pexels), íconos con licencia (Heroicons, Lucide, Phosphor, Font Awesome free). NUNCA copiar de otros temas vendidos.
4. **Fuentes**: Google Fonts o auto-hosted, licencia compatible.
5. **Animaciones suaves**: prefers-reduced-motion respetado.
6. **No tracking**: sin Google Analytics ni equivalentes hardcoded.
7. **Comentarios HTML**: secciones identificadas con comentarios para facilitar al comprador editar.

## Documentación HTML obligatoria

Secciones que **deben** aparecer:

1. Welcome / Thank you
2. Getting started (estructura de archivos)
3. HTML/CSS/JS structure
4. Customización (colores, tipografía, layout)
5. Cómo añadir/quitar páginas y componentes
6. Plugins y librerías usadas con enlaces
7. Sources / Credits
8. Changelog
9. Support

## Preview y demo

- **Preview en GIF/PNG** (590x300 obligatorio Envato, 80x80 favicon).
- **Live demo** en URL pública (Netlify/Cloudflare Pages/GH Pages).
- **Screenshots** de cada layout principal (mín. 1920x1200, png o jpg).

## Precio sugerido (2026)

- Standard site templates: **$24 – $59**.
- Premium con muchas variantes/admin/dashboard: **$59 – $129**.

## Naming / SEO del listing

- Título: `Nombre — Tipo de template (stack)`. Ej: `Aurora — SaaS & Agency NextJS Template`.
- Tags: 10–14 tags relevantes (stack, tipo, sector, color, estilo).
- Keywords frecuentes: `responsive`, `clean`, `modern`, `landing`, `multipurpose`, `dashboard`, `saas`, `tailwind`, `nextjs`, `react`, etc.

## Anti-rechazo (cosas que tumban una review)

- Inconsistencias en spacing entre secciones (margenes random).
- Tipografía: usar máximo 2 familias.
- Colores: paleta documentada (4–6 colores principales + grises).
- Botones: estados hover/active/focus/disabled visibles.
- Formularios: validación cliente + estilos de error.
- 404 / Coming Soon / Maintenance: si es admin/landing, incluir variantes.
- Imágenes optimizadas (WebP o AVIF + fallback).
