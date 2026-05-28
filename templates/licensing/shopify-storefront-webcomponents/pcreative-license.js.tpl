/**
 * pcreative-license.js — license client for Shopify Storefront Web Components.
 *
 * Same JWT verify offline (RS256 + SubtleCrypto) pattern as the Liquid
 * version, but plugs into the Web Components flow: BEFORE the official
 * `<script type="module" src="https://cdn.shopify.com/storefront/web-components.esm.js">`
 * runs, we validate the license. If invalid, we hide all `shopify-*`
 * components from the page and show a watermark.
 *
 * Embed in <head> with: <script defer src="assets/pcreative-license.js"></script>
 */
(function () {
  "use strict";

  var PUBKEY_PEM = "__LICENSE_PUBKEY__";
  var EXPECTED_ISSUER = "__LICENSE_ISSUER__";
  var EXPECTED_PRODUCT = "__SLUG__";
  var LICENSE_API_URL = "__LICENSE_API_URL__";
  var STORAGE_KEY = "pcreative.license.__SLUG__";

  function b64UrlToBytes(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    var raw = atob(s);
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }
  function b64UrlToString(s) { return new TextDecoder().decode(b64UrlToBytes(s)); }
  function pemToBinary(pem) {
    var clean = pem.replace(/-----BEGIN PUBLIC KEY-----/g, "")
                   .replace(/-----END PUBLIC KEY-----/g, "")
                   .replace(/\s+/g, "");
    return Uint8Array.from(atob(clean), function (c) { return c.charCodeAt(0); }).buffer;
  }
  async function importKey() {
    return crypto.subtle.importKey("spki", pemToBinary(PUBKEY_PEM),
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  }
  async function verifyJWT(token) {
    var parts = token.split("."); if (parts.length !== 3) throw new Error("malformed");
    var key = await importKey();
    var sig = b64UrlToBytes(parts[2]);
    var data = new TextEncoder().encode(parts[0] + "." + parts[1]);
    if (!(await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, sig, data)))
      throw new Error("bad sig");
    var claims = JSON.parse(b64UrlToString(parts[1]));
    if (claims.iss !== EXPECTED_ISSUER) throw new Error("bad iss");
    if (claims.product !== EXPECTED_PRODUCT) throw new Error("bad product");
    if (claims.exp && Date.now() >= claims.exp * 1000) throw new Error("expired");
    return claims;
  }

  async function activate(code, domain) {
    var r = await fetch(LICENSE_API_URL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: code, product: EXPECTED_PRODUCT, domain: domain }),
    });
    if (!r.ok) throw new Error("activate http " + r.status);
    var json = await r.json();
    if (!json.valid || !json.jwt) throw new Error("invalid");
    return json.jwt;
  }

  function watermark() {
    var el = document.createElement("div");
    el.style.cssText = "position:fixed;bottom:8px;right:8px;background:#fef3c7;color:#92400e;padding:6px 10px;border:1px solid #f59e0b;border-radius:6px;font:11px/1.2 system-ui;z-index:2147483647;";
    el.textContent = "Storefront Web Components — Unlicensed copy of __PROJECT__";
    document.body.appendChild(el);
  }

  function hideComponents() {
    document.querySelectorAll("[data-pcreative-gated='true']").forEach(function (el) {
      el.style.display = "none";
    });
    // Remove all `<shopify-*>` to prevent any data fetch.
    document.querySelectorAll("[is^='shopify-'], shopify-context, shopify-product, shopify-collection, shopify-cart").forEach(function (el) {
      el.remove();
    });
  }

  window.pcreativeLicense = { state: { ready: false, valid: false } };

  async function boot() {
    var domain = location.host;
    var purchaseCode = window.__PCREATIVE_LICENSE_CODE || (document.querySelector("[data-pcreative-license-code]") || {}).dataset?.pcreativeLicenseCode;
    var cached = null;
    try { cached = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"); } catch (e) {}

    if (cached && cached.jwt) {
      try {
        var claims = await verifyJWT(cached.jwt);
        if (claims.domain === domain) {
          window.pcreativeLicense.state = { ready: true, valid: true, claims: claims };
          return;
        }
      } catch (e) {}
    }

    if (!purchaseCode) {
      window.pcreativeLicense.state = { ready: true, valid: false, error: "no code" };
      hideComponents(); watermark(); return;
    }

    try {
      var jwt = await activate(purchaseCode, domain);
      var c = await verifyJWT(jwt);
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ jwt: jwt, code: purchaseCode })); } catch (e) {}
      window.pcreativeLicense.state = { ready: true, valid: true, claims: c };
    } catch (e) {
      window.pcreativeLicense.state = { ready: true, valid: false, error: String(e) };
      hideComponents(); watermark();
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
