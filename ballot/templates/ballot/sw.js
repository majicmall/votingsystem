// ATL's Hottest App — LAUNCH-010
// Minimal service worker foundation.
// No fetch interception, offline caching, or background synchronization.

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
