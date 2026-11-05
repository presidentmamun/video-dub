// Video Dubbing: makes the page "cross-origin isolated" so its video tool can use every processor core.
// It only adds two headers to the page itself (COOP and COEP "credentialless"); every other request passes through untouched.
// This works on any web host, without changing the server. Browsers without "credentialless" (Safari) just keep one core.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith((async () => {
    const r = await fetch(e.request);
    if (r.type === 'opaqueredirect' || r.status === 0) return r;
    const h = new Headers(r.headers);
    h.set('Cross-Origin-Opener-Policy', 'same-origin');
    h.set('Cross-Origin-Embedder-Policy', 'credentialless');
    return new Response(r.body, { status: r.status, statusText: r.statusText, headers: h });
  })());
});
