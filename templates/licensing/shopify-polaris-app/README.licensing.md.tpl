# __PROJECT__ — License system (Polaris App)

Server-side license verification para apps Shopify embebidas. Mismo
patrón que Hydrogen pero cacheando el JWT en Prisma (compartido entre
procesos).

## Files

- `app/lib/license.server.ts` — verify offline + activate/heartbeat.
- `app/routes/app.license.tsx` — UI Polaris para ver/refrescar estado.
- `prisma/migrations/license.sql` — schema del modelo `License`.
- `.env.example` — `PCREATIVE_LICENSE_*` añadidas.

## Setup

1. Añade `jose` a deps:
   ```bash
   npm i jose
   ```

2. Pega el modelo `License` en `prisma/schema.prisma` (ver `license.migration.sql`):
   ```prisma
   model License {
     shop          String   @id
     jwt           String
     lastHeartbeat DateTime @default(now())
     watermark     String   @default("")
     updatedAt     DateTime @updatedAt
   }
   ```

3. `npx prisma migrate dev --name add_license`.

4. Pon tu key en `.env`:
   ```
   PCREATIVE_LICENSE_KEY=tu-key
   ```

5. Llama a `getLicenseStatus(shop)` en cualquier loader que quieras gatear.

## Para Checkout UI Extensions

El mismo archivo `app/lib/license.server.ts` sirve. La extension corre
sandboxed → la validación se hace en el parent app loader. Las
extensions pueden leer del cache Prisma via la app embedded.
