/* ============================================================================
 * native.js — Capa nativa (solo se activa dentro de la app Capacitor).
 * Registra el token de push y lo manda al gateway (/push/register) para que el
 * servidor pueda avisar "build terminado". En navegador normal no hace nada.
 * ========================================================================== */
(function () {
  const Cap = window.Capacitor;
  if (!Cap || !Cap.isNativePlatform || !Cap.isNativePlatform()) return;

  const cfg = () => { try { return JSON.parse(localStorage.getItem('tf_remote') || '{}'); } catch (e) { return {}; } };
  const PN = Cap.Plugins && Cap.Plugins.PushNotifications;
  if (!PN) return;

  async function sendToken(token) {
    const c = cfg();
    if (!c.base) return;   // aún sin configurar el gateway
    try {
      await fetch(c.base.replace(/\/$/, '') + '/push/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (c.token || '') },
        body: JSON.stringify({ token, platform: Cap.getPlatform() }),
      });
      console.log('[native] push token registrado');
    } catch (e) { console.warn('[native] push register falló', e); }
  }

  PN.addListener('registration', (t) => sendToken(t.value));
  PN.addListener('registrationError', (e) => console.warn('[native] push reg error', e));
  PN.addListener('pushNotificationReceived', (n) => console.log('[native] push recibida', n));
  PN.addListener('pushNotificationActionPerformed', (n) => console.log('[native] push tap', n));

  (async () => {
    try {
      let perm = await PN.checkPermissions();
      if (perm.receive !== 'granted') perm = await PN.requestPermissions();
      if (perm.receive === 'granted') await PN.register();
    } catch (e) { console.warn('[native] push init falló', e); }
  })();

  // Expuesto por si el día de mañana queremos cámara nativa (hoy el OCR usa
  // <input capture> del WebView, que ya funciona). Lo dejamos preparado:
  window.tfNativePlatform = Cap.getPlatform();
})();
