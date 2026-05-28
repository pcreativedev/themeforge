/**
 * license.server.ts — pcreative license verification for Shopify Polaris App.
 *
 * Same offline RS256 verify as Hydrogen, but caches the JWT in Prisma
 * so multiple processes share the cache. Use in app/shopify.server.ts
 * or any loader that needs gating.
 */
import { jwtVerify, importSPKI } from "jose";
import db from "./db.server";  // Prisma instance — ya viene del scaffold

const LICENSE_API_URL = "__LICENSE_API_URL__";
const PUBKEY_PEM = `__LICENSE_PUBKEY__`;
const ISSUER = "__LICENSE_ISSUER__";
const PRODUCT = "__SLUG__";
const HEARTBEAT_MS = 24 * 60 * 60 * 1000;

async function verifyOffline(jwt: string, domain: string) {
  const key = await importSPKI(PUBKEY_PEM, "RS256");
  const { payload } = await jwtVerify(jwt, key, { issuer: ISSUER });
  if ((payload as any).product !== PRODUCT) throw new Error("product mismatch");
  if ((payload as any).domain !== domain) throw new Error("domain mismatch");
  return payload;
}

async function activate(code: string, domain: string) {
  const r = await fetch(LICENSE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ license_key: code, product: PRODUCT, domain }),
  });
  if (!r.ok) throw new Error(`activate http ${r.status}`);
  const json = await r.json();
  if (!json.valid || !json.jwt) throw new Error("invalid response");
  return json.jwt as string;
}

export async function getLicenseStatus(shopDomain: string) {
  const code = process.env.PCREATIVE_LICENSE_KEY;
  if (!code) return { valid: false, error: "no PCREATIVE_LICENSE_KEY" };

  const cached = await db.license.findUnique({ where: { shop: shopDomain } });
  if (cached && Date.now() - cached.lastHeartbeat.getTime() < HEARTBEAT_MS) {
    try {
      const claims = await verifyOffline(cached.jwt, shopDomain);
      return { valid: true, claims };
    } catch (e) {
      // cache stale — re-activate
    }
  }

  try {
    const jwt = await activate(code, shopDomain);
    const claims = await verifyOffline(jwt, shopDomain);
    await db.license.upsert({
      where: { shop: shopDomain },
      create: { shop: shopDomain, jwt, lastHeartbeat: new Date(), watermark: (claims as any).watermark || "" },
      update: { jwt, lastHeartbeat: new Date(), watermark: (claims as any).watermark || "" },
    });
    return { valid: true, claims };
  } catch (e) {
    return { valid: false, error: String(e) };
  }
}
