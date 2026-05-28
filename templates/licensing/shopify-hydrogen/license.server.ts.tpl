/**
 * license.server.ts — pcreative license verification for Hydrogen.
 *
 * Server-side: env vars PCREATIVE_LICENSE_KEY + PCREATIVE_LICENSE_API.
 * Verifies the JWT offline with the embedded RS256 public key via jose.
 * Use in app/entry.server.tsx or root loader.
 */
import { jwtVerify, importSPKI } from "jose";

const LICENSE_API_URL = "__LICENSE_API_URL__";
const PUBKEY_PEM = `__LICENSE_PUBKEY__`;
const ISSUER = "__LICENSE_ISSUER__";
const PRODUCT = "__SLUG__";
const HEARTBEAT_MS = 24 * 60 * 60 * 1000;

type LicenseClaims = {
  sub: string;
  product: string;
  domain: string;
  type: "regular" | "extended";
  watermark: string;
  exp: number;
  iss: string;
};

let cachedJwt: string | null = null;
let cachedClaims: LicenseClaims | null = null;
let lastHeartbeat = 0;

async function verifyOffline(jwt: string, domain: string): Promise<LicenseClaims> {
  const key = await importSPKI(PUBKEY_PEM, "RS256");
  const { payload } = await jwtVerify(jwt, key, { issuer: ISSUER, audience: PRODUCT });
  const c = payload as unknown as LicenseClaims;
  if (c.product !== PRODUCT) throw new Error("product mismatch");
  if (c.domain !== domain) throw new Error("domain mismatch");
  return c;
}

async function activate(code: string, domain: string): Promise<string> {
  const r = await fetch(LICENSE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ license_key: code, product: PRODUCT, domain }),
  });
  if (!r.ok) throw new Error(`activate http ${r.status}`);
  const json = (await r.json()) as { valid: boolean; jwt: string };
  if (!json.valid || !json.jwt) throw new Error("invalid response");
  return json.jwt;
}

export async function getLicenseStatus(domain: string) {
  const code = process.env.PCREATIVE_LICENSE_KEY;
  if (!code) return { valid: false, error: "no PCREATIVE_LICENSE_KEY" };

  // Cache hit + heartbeat válido
  if (cachedJwt && cachedClaims && Date.now() - lastHeartbeat < HEARTBEAT_MS) {
    try {
      await verifyOffline(cachedJwt, domain);
      return { valid: true, claims: cachedClaims };
    } catch (e) {
      cachedJwt = cachedClaims = null;
    }
  }

  // Activate / refresh
  try {
    const jwt = await activate(code, domain);
    const claims = await verifyOffline(jwt, domain);
    cachedJwt = jwt;
    cachedClaims = claims;
    lastHeartbeat = Date.now();
    return { valid: true, claims };
  } catch (e) {
    return { valid: false, error: String(e) };
  }
}

export function isLicenseValid() {
  return cachedClaims !== null && Date.now() - lastHeartbeat < HEARTBEAT_MS;
}
