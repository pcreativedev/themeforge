/* Service worker mínimo: cachea el shell para que la PWA abra offline.
   Las llamadas a la API (/rpc, /ws, /upload) NUNCA se cachean. */
const CACHE = 'tf-mobile-v1';
const SHELL = [
  './index.html', './app.jsx', './manifest.webmanifest',
  '../remote/tfbridge-remote.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) =>
    Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // No tocar la API ni websockets
  if (e.request.method !== 'GET' || /\/(rpc|ws|upload|health)$/.test(url.pathname)) return;
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match('./index.html')))
  );
});
