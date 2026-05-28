# __PROJECT__ — License system (Shopify Functions)

Pre-deploy hook que **bloquea `npm run deploy`** si no hay licencia válida.
Sin licencia → exit 1 → npm script falla → Shopify Functions no se
publican.

## Files

- `scripts/pre-deploy-license-check.mjs` — el check.
- `.env.example` — `PCREATIVE_LICENSE_*` añadidas.
- `package.json` — scripts `prebuild` + `predeploy` enganchan el check.

## Setup

1. `npm i jose`.
2. Añade tu key a `.env`:
   ```
   PCREATIVE_LICENSE_KEY=tu-key
   ```
3. Cualquier `npm run build` o `npm run deploy` ejecutará el check primero.

## Por qué pre-deploy y no runtime

Functions corren **dentro de Shopify** — no podemos hacer fetch a tu
backend desde el Wasm en runtime. La protección efectiva es:

1. **Pre-deploy**: bloquear el publish sin licencia válida.
2. **Backend**: gate el download del repo de Functions (lo gestiona tu
   pcreative panel via `/api/download?product=__SLUG__&jwt=...`).

Así, sin licencia: nadie puede ni bajar el código fuente ni publicar la
Function al merchant.
