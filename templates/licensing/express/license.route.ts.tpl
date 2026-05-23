// Licensing — verification route.
//
// Mount this on your Hono / Express / NestJS / Elysia app. Below is a
// Hono variant; adapt to your framework's idiom (the body is what
// matters).

const LICENSE_API_URL = '__LICENSE_API_URL__';
const PRODUCT_SLUG = '__SLUG__';

export async function verifyLicense(payload: {
  license_key: string;
  product?: string;
  domain?: string;
}) {
  if (!payload.license_key) {
    return { valid: false, error: 'Purchase code is required' as const };
  }
  try {
    const res = await fetch(LICENSE_API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        license_key: payload.license_key,
        product: payload.product ?? PRODUCT_SLUG,
        domain: payload.domain ?? 'localhost',
      }),
    });
    return await res.json();
  } catch {
    return {
      valid: false as const,
      error: 'Unable to contact license server.',
    };
  }
}

// ── Hono example ─────────────────────────────────────────────────────
//
// import { Hono } from 'hono';
// import { verifyLicense } from './routes/license';
//
// const app = new Hono();
// app.post('/api/verify-license', async (c) => {
//   const body = await c.req.json();
//   const host = new URL(c.req.url).host;
//   return c.json(await verifyLicense({ ...body, domain: body.domain ?? host }));
// });
//
// ── Express example ──────────────────────────────────────────────────
//
// import express from 'express';
// import { verifyLicense } from './routes/license';
//
// const app = express();
// app.use(express.json());
// app.post('/api/verify-license', async (req, res) => {
//   res.json(await verifyLicense({ ...req.body, domain: req.body.domain ?? req.hostname }));
// });
