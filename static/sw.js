const CACHE = "caloritrack-v1";
const STATIC = ["/", "/index.html", "/manifest.json", "/icon-180.png", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Always go network-first for API calls
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(fetch(e.request).catch(() =>
      new Response(JSON.stringify({error: "offline"}), {headers: {"Content-Type": "application/json"}})
    ));
    return;
  }
  // Cache-first for static assets, network fallback
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      });
    })
  );
});
