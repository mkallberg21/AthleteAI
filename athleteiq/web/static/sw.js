/**
 * Service worker: app shell caching and push delivery.
 *
 * Static assets are cache-first so the capture screen opens instantly with no
 * connection. API requests are never cached -- stale leaderboards and stale
 * assignment progress are worse than absent ones, and the pages handle a failed
 * fetch by showing what they already have.
 */

const CACHE = 'athleteiq-shell-v1';

const SHELL = [
  './',
  'index.html',
  'capture.html',
  'coach.html',
  'parent.html',
  'leaderboard.html',
  'styles.css',
  'api.js',
  'counter.js',
  'offline.js',
  'manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    // Individually, so one 404 does not abort the whole install.
    caches.open(CACHE).then((cache) => Promise.all(
      SHELL.map((url) => cache.add(url).catch(() => null))
    )).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache the API. A cached roster or assignment progress read as
  // current would be actively misleading.
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        // Refresh in the background so the next open is current.
        fetch(request)
          .then((res) => {
            if (res && res.ok) caches.open(CACHE).then((c) => c.put(request, res.clone()));
          })
          .catch(() => {});
        return cached;
      }
      return fetch(request)
        .then((res) => {
          if (res && res.ok && res.type === 'basic') {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch(() => caches.match('capture.html'));
    })
  );
});

self.addEventListener('push', (event) => {
  let data = { title: 'AthleteIQ', body: '', link: 'capture.html' };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch {
    if (event.data) data.body = event.data.text();
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      badge: 'icon-192.png',
      icon: 'icon-192.png',
      data: { link: data.link },
      tag: data.title,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const link = (event.notification.data && event.notification.data.link) || 'capture.html';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Focus an open tab rather than stacking up new ones.
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      return self.clients.openWindow(link);
    })
  );
});
