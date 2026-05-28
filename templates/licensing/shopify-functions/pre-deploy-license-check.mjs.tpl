#!/usr/bin/env node
/**
 * pre-deploy-license-check.mjs — gate `shopify app deploy` con licencia válida.
 *
 * Lee PCREATIVE_LICENSE_KEY del entorno, lo intercambia por un JWT
 * firmado, verifica offline y permite el deploy SOLO si todo va bien.
 * Sin licencia válida → exit 1 → npm script falla → deploy bloqueado.
 *
 * Registra hooks en package.json:
 *   "scripts": {
 *     "prebuild":  "node scripts/pre-deploy-license-check.mjs",
 *     "predeploy": "node scripts/pre-deploy-license-check.mjs"
 *   }
 */
import { jwtVerify, importSPKI } from "jose";

const LICENSE_API_URL = "__LICENSE_API_URL__";
const PUBKEY_PEM = `__LICENSE_PUBKEY__`;
const ISSUER = "__LICENSE_ISSUER__";
const PRODUCT = "__SLUG__";

const code = process.env.PCREATIVE_LICENSE_KEY;
if (!code) {
  console.error("\n❌ pcreative license: PCREATIVE_LICENSE_KEY no está en el entorno.");
  console.error("   Añádela a .env (PCREATIVE_LICENSE_KEY=<tu-key>) y vuelve a intentar.\n");
  process.exit(1);
}

const domain = process.env.PCREATIVE_LICENSE_DOMAIN || "shopify-functions-deploy.local";

try {
  console.log(`\n→ pcreative license: validando ${PRODUCT} en ${domain}...`);
  const r = await fetch(LICENSE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ license_key: code, product: PRODUCT, domain }),
  });
  if (!r.ok) {
    console.error(`❌ activate HTTP ${r.status}`);
    process.exit(1);
  }
  const json = await r.json();
  if (!json.valid || !json.jwt) {
    console.error("❌ respuesta inválida del backend");
    process.exit(1);
  }
  const key = await importSPKI(PUBKEY_PEM, "RS256");
  const { payload } = await jwtVerify(json.jwt, key, { issuer: ISSUER });
  if (payload.product !== PRODUCT) {
    console.error(`❌ JWT product mismatch: ${payload.product} ≠ ${PRODUCT}`);
    process.exit(1);
  }
  console.log(`✓ pcreative license válida — type=${payload.type}, exp=${new Date(payload.exp * 1000).toISOString()}, watermark=${payload.watermark}`);
  process.exit(0);
} catch (e) {
  console.error(`❌ pcreative license error: ${e.message}`);
  process.exit(1);
}
