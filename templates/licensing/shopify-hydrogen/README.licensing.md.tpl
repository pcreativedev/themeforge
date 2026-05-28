# __PROJECT__ — License system (Hydrogen)

Server-side license verification para storefronts headless con Hydrogen.

## Files

- `app/lib/license.server.ts` — verify offline RS256 con jose + activate/heartbeat.
- `app/routes/admin.license._index.tsx` — UI admin para ver el estado.
- `.env.example` — añadidas `PCREATIVE_LICENSE_*` env vars.

## Setup

1. Añade `jose` a deps:
   ```bash
   npm i jose
   ```

2. Pon tu license key en `.env`:
   ```
   PCREATIVE_LICENSE_KEY=tu-key
   PCREATIVE_LICENSE_API=__LICENSE_API_URL__
   ```

3. Llama a `getLicenseStatus()` en el root loader o en cualquier ruta
   donde quieras gatear:

   ```ts
   // app/root.tsx
   import { getLicenseStatus } from "~/lib/license.server";

   export async function loader({ request, context }: LoaderFunctionArgs) {
     const status = await getLicenseStatus(new URL(request.url).host);
     if (!status.valid) throw new Response("License invalid", { status: 403 });
     // ...
   }
   ```

4. Visita `/admin/license` para verificar el estado.

## Watermark + tracking

La función `getLicenseStatus` devuelve `claims.watermark` — un ID único
por licencia. Puedes inyectarlo como meta tag invisible para trazar
filtraciones:

```tsx
{status.valid && <meta name="pcre-w" content={status.claims.watermark} />}
```
