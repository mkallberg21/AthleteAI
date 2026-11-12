/**
 * Service worker: app shell caching and push delivery.
 *
 * Static assets are cache-first so the capture screen opens instantly with no
 * connection. API requests are never cached -- stale leaderboards and stale
 * assignment progress are worse than absent ones, and the pages handle a failed
 * fetch by showing what they already have.
 */

const CACHE = 'offdays-shell-v12';

// Pages where the server enforces rules the page must match (agree to terms at sign-up, the director's dashboard,
// the parent's consent screens). A saved copy of one of these from before a release shows the old form while the
// server asks for the new one, so they are fetched fresh when there is a connection and only fall back to the saved
// copy when there is none. The athlete's capture screen is deliberately NOT here: it has to open instantly with no
// signal, in a driveway.
const NETWORK_FIRST = ['index.html', 'coach.html', 'parent.html'];
const NETWORK_FIRST_MS = 4000;

const SHELL = [
  './',
  'index.html',
  'capture.html',
  'coach.html',
  'parent.html',
  'styles.css',
  'offdays-lockup.png',
  'offdays-mark.png',
  // The typefaces are part of the shell. Without them a capture screen
  // opened with no connection falls back to a system face, which is a
  // different-looking app at exactly the moment it is least reassuring.
  'fonts/fonts.css',
  'fonts/inter-400-latin.woff2',
  'fonts/inter-500-latin.woff2',
  'fonts/inter-600-latin.woff2',
  'fonts/barlow-condensed-600-latin.woff2',
  'fonts/barlow-condensed-700-latin.woff2',
  'fonts/jetbrains-mono-400-latin.woff2',
  'api.js',
  'counter.js',
  // Wall ball counts by ear. The worklet is only fetched the first time a
  // wall-ball drill opens the microphone, which may well be in a driveway.
  'sound.js',
  'sound-worklet.js',
  // Shooting speed is imported by the capture screen, so a missing copy
  // would stop the whole screen loading offline, not just shooting.
  'shotspeed.js',
  // The setup check before Start; imported by the capture screen as well.
  'setup.js',
  // Shooting distance: what the camera saw of the goal and the shooter.
  // The estimate itself is made on the server; distance.js is the bench copy.
  'scene.js',
  'review.js',
  // Typing a roster in by hand: imported by the coach page.
  'roster_entry.js',
  // Setting up many teams at once, imported by the coach page.
  'setup_flow.js',
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

// Fresh when online (within a few seconds), the saved copy when not. A page that answers late or fails never leaves
// the user with nothing: the saved copy is the fallback for both.
function networkFirst(request) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), NETWORK_FIRST_MS);
  return fetch(request, { signal: ctl.signal, cache: 'no-store' })
    .then((res) => {
      clearTimeout(timer);
      if (res && res.ok && res.type === 'basic') {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(request, copy));
      }
      return res;
    })
    .catch(() => {
      clearTimeout(timer);
      return caches.match(request).then((cached) => cached || caches.match('capture.html'));
    });
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache the API. A cached roster or assignment progress read as
  // current would be actively misleading.
  if (url.pathname.startsWith('/api/')) return;

  const last = url.pathname.split('/').pop() || 'index.html';
  if (NETWORK_FIRST.includes(last)) {
    event.respondWith(networkFirst(request));
    return;
  }

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
  let data = { title: '0FFDAYS', body: '', link: 'capture.html' };
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
