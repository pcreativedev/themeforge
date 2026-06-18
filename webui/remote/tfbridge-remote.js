/* ============================================================================
 * tfbridge-remote.js — Reimplementa window.tfBridge sobre el API Gateway remoto.
 *
 * Permite que la MISMA WebUI (neotokyo/matrix/kawaii) funcione contra el motor
 * en un VPS/PC en vez del puente nativo QWebChannel. Carga este script ANTES de
 * los screens y NO cargues qwebchannel: el resto del código (callB, *_event) no
 * cambia, porque exponemos la misma forma (métodos → Promise<JSON string>,
 * señales con .connect/.disconnect).
 *
 * Config:  window.TF_REMOTE = { base: "http://VPS:8765", token: "…" }
 *          (con Tailscale, base = http://<nodo-tailnet>:8765)
 * ========================================================================== */
(function () {
  const CFG = window.TF_REMOTE || {};
  const BASE = (CFG.base || (location.origin)).replace(/\/$/, '');
  const TOKEN = CFG.token || '';
  const WS_URL = BASE.replace(/^http/, 'ws') + '/ws' + (TOKEN ? '?token=' + encodeURIComponent(TOKEN) : '');

  // ---- señal estilo Qt (connect/disconnect) --------------------------------
  function Signal() {
    const subs = new Set();
    return {
      connect: (cb) => subs.add(cb),
      disconnect: (cb) => subs.delete(cb),
      _emit: (payload) => subs.forEach(cb => { try { cb(JSON.stringify(payload)); } catch (e) {} }),
    };
  }
  const leads_event = Signal();
  const gen_event = Signal();
  const build_done = Signal();
  const build_event = Signal();   // logs en vivo de create_build / suggest_stack

  // qué señal y "op" corresponde a cada método de streaming
  const STREAM_MAP = {
    leads_search:     { sig: leads_event, op: 'search' },
    leads_enrich:     { sig: leads_event, op: 'enrich' },
    leads_enrich_all: { sig: leads_event, op: 'enrich_all' },
    gen_extract:      { sig: gen_event,   op: 'extract' },
    gen_ocr:          { sig: gen_event,   op: 'ocr' },
    gen_generate:     { sig: build_done,  op: 'generate' },
    suggest_stack:    { sig: build_event, op: 'suggest' },
    create_build:     { sig: build_event, op: 'build' },
  };

  // ---- WebSocket con reconexión + cola --------------------------------------
  let ws = null, ready = false, seq = 1;
  const pending = new Map();   // id → {method, resolve}
  const queue = [];

  function connect() {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => { ready = true; while (queue.length) ws.send(queue.shift()); };
    ws.onclose = () => { ready = false; setTimeout(connect, 1500); };  // reconexión simple
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      const info = pending.get(m.id);
      const map = info && STREAM_MAP[info.method];
      if (m.event !== undefined && map) {
        // eventos en vivo: progress, log, phase, started, stack_suggested…
        map.sig._emit({ op: map.op, event: m.event, ...(m.data || {}) });
      } else if (m.result !== undefined) {
        if (map) map.sig._emit({ op: map.op, done: true, ...m.result });
        if (info) { info.resolve(JSON.stringify(m.result)); pending.delete(m.id); }
      } else if (m.error !== undefined) {
        if (map) map.sig._emit({ op: map.op, done: true, ok: false, error: m.error });
        if (info) { info.resolve(JSON.stringify({ ok: false, error: m.error })); pending.delete(m.id); }
      }
    };
  }
  connect();

  function wsSend(method, params) {
    const id = seq++;
    return new Promise((resolve) => {
      pending.set(id, { method, resolve });
      const frame = JSON.stringify({ id, method, params });
      if (ready) ws.send(frame); else queue.push(frame);
    });
  }

  async function httpRpc(method, params) {
    try {
      const r = await fetch(BASE + '/rpc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN },
        body: JSON.stringify({ id: seq++, method, params }),
      });
      const j = await r.json();
      return JSON.stringify(j.result !== undefined ? j.result : { ok: false, error: j.error || ('HTTP ' + r.status) });
    } catch (e) { return JSON.stringify({ ok: false, error: '' + e }); }
  }

  // ---- métodos: misma firma que el bridge nativo (args posicionales) -------
  // Síncronos van por HTTP; los de streaming arrancan por WS y devuelven {running}.
  const M = {
    // leads (sync)
    leads_list:       (f) => httpRpc('leads_list', JSON.parse(f || '{}')),
    leads_stats:      () => httpRpc('leads_stats', {}),
    leads_update:     (id, status, notes) => httpRpc('leads_update', { id, status, notes }),
    leads_delete:     (id) => httpRpc('leads_delete', { id }),
    leads_export:     (f) => httpRpc('leads_export', JSON.parse(f || '{}')),
    leads_save_key:   (key) => httpRpc('leads_save_key', { key }),
    leads_key_status: () => httpRpc('leads_key_status', {}),
    // leads (stream)
    leads_search:     (query, location, max) => { wsSend('leads_search', { query, location, max }); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    leads_enrich:     (id) => { wsSend('leads_enrich', { id }); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    leads_enrich_all: () => { wsSend('leads_enrich_all', {}); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    // generador (sync)
    gen_brief_list:   () => httpRpc('gen_brief_list', {}),
    gen_brief_get:    (id) => httpRpc('gen_brief_get', { id }),
    gen_brief_save:   (f) => httpRpc('gen_brief_save', JSON.parse(f || '{}')),
    gen_brief_delete: (id) => httpRpc('gen_brief_delete', { id }),
    gen_recommend:    (f) => httpRpc('gen_recommend', JSON.parse(f || '{}')),
    // generador (stream)
    gen_extract:      (f) => { wsSend('gen_extract', JSON.parse(f || '{}')); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    gen_ocr:          (path, kind) => { wsSend('gen_ocr', { image_path: path, kind: kind || '' }); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    gen_generate:     (f) => { wsSend('gen_generate', JSON.parse(f || '{}')); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    // crear proyecto (Vibe / Recreate / Stack)
    list_stacks:      () => httpRpc('list_stacks', {}),
    suggest_stack:    (f) => { wsSend('suggest_stack', JSON.parse(f || '{}')); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    create_build:     (f) => { wsSend('create_build', JSON.parse(f || '{}')); return Promise.resolve(JSON.stringify({ ok: true, running: true })); },
    // cámara: en móvil, el file picker nativo es del cliente (Capacitor) → sube
    // a /upload y devuelve la ruta. Aquí, fallback: pide URL.
    gen_pick_image:   async () => {
      if (window.tfPickImage) { const p = await window.tfPickImage(); return JSON.stringify({ ok: !!p, path: p || '' }); }
      const u = prompt('Ruta/URL de la imagen de la carta:'); return JSON.stringify({ ok: !!u, path: u || '' });
    },
    ping: (msg) => Promise.resolve(JSON.stringify({ pong: msg })),
  };

  window.tfBridge = Object.assign(M, { leads_event, gen_event, build_done, build_event });
  console.log('[tfbridge-remote] activo →', BASE);
})();
