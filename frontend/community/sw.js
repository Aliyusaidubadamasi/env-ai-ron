/* App-shell cache + network-first data. Keeps the app usable on weak connections. */
const SHELL = "envairon-shell-v1";
const FILES = ["./", "style.css", "app.js", "manifest.webmanifest", "icon.svg", "/vendor/leaflet/leaflet.js", "/vendor/leaflet/leaflet.css"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL && k !== "envairon-data").map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (url.pathname.startsWith("/api/v1/community/")) {   // data: network first, fall back to last copy
    e.respondWith(fetch(req).then((r) => { const c = r.clone(); caches.open("envairon-data").then((x) => x.put(req, c)); return r; })
      .catch(() => caches.match(req)));
    return;
  }
  if (url.origin === location.origin) e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
});
