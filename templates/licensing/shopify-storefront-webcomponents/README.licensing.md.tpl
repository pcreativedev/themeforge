# __PROJECT__ — License system (Web Components)

Same 6-layer anti-nulled licensing as the Liquid stack, adapted to the
Storefront Web Components flow. Sin licencia válida, los componentes
`<shopify-*>` se **eliminan del DOM antes de hidratar** y aparece un
watermark visible.

## Files

- `assets/pcreative-license.js` — JWT verify offline + watermark.
- `README.licensing.md` — este archivo.

## Setup

1. Pega el purchase code en `index.html` antes del `</head>`:

   ```html
   <script>window.__PCREATIVE_LICENSE_CODE = "PASTE-HERE";</script>
   ```

   O en cualquier elemento con `data-pcreative-license-code="..."`.

2. Replace placeholders `__LICENSE_API_URL__`, `__LICENSE_PUBKEY__`,
   `__LICENSE_ISSUER__` en `assets/pcreative-license.js` con los valores
   de tu backend.

## Cómo funciona

1. `pcreative-license.js` carga primero (defer).
2. Lee el code → POST a `<LICENSE_API_URL>` → recibe JWT.
3. Verifica JWT con la pubkey embebida (zero deps).
4. Si valid: deja que `web-components.esm.js` hidrate.
5. Si invalid: elimina todos los `<shopify-*>` del DOM + watermark.
