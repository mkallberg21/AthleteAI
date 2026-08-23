/**
 * Offline capture support.
 *
 * Two problems have to be solved for a phone in a driveway with one bar:
 *
 *  1. **Starting a session needs a nonce from the server.** So the client keeps
 *     a small pool of pre-reserved slots in IndexedDB, topped up whenever it
 *     has signal, and spends one when it doesn't.
 *
 *  2. **Finishing a session needs to reach the server.** So a completed session
 *     goes into a durable queue first and is flushed opportunistically. The
 *     submit endpoint is idempotent on the nonce, which is what makes retrying
 *     safe -- a duplicate delivery replays the original result instead of
 *     scoring twice.
 *
 * Everything here survives the tab closing, the phone sleeping, and the browser
 * being killed. localStorage would not survive a large queue, and losing a
 * session loses a streak, which loses the athlete.
 */

const DB_NAME = 'athleteiq';
const DB_VERSION = 1;
const SLOTS = 'slots';
const QUEUE = 'queue';

/** Slots to keep banked per drill. Two covers a session plus a retry. */
export const SLOT_TARGET = 2;

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(SLOTS)) {
        const store = db.createObjectStore(SLOTS, { keyPath: 'session_id' });
        store.createIndex('drill_key', 'drill_key', { unique: false });
      }
      if (!db.objectStoreNames.contains(QUEUE)) {
        db.createObjectStore(QUEUE, { keyPath: 'session_id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function tx(store, mode, fn) {
  return openDb().then((db) => new Promise((resolve, reject) => {
    const transaction = db.transaction(store, mode);
    const result = fn(transaction.objectStore(store));
    transaction.oncomplete = () => resolve(result && result.result !== undefined ? result.result : result);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  }));
}

// --------------------------------------------------------------- slot pool

export async function putSlots(slots) {
  await tx(SLOTS, 'readwrite', (store) => {
    slots.forEach((slot) => store.put(slot));
  });
}

export async function countSlots(drillKey) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const req = db.transaction(SLOTS, 'readonly')
      .objectStore(SLOTS).index('drill_key').count(IDBKeyRange.only(drillKey));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Claim a banked slot for this drill, removing it so it is never reused. */
export async function takeSlot(drillKey) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(SLOTS, 'readwrite');
    const store = transaction.objectStore(SLOTS);
    const req = store.index('drill_key').openCursor(IDBKeyRange.only(drillKey));
    let claimed = null;
    req.onsuccess = () => {
      const cursor = req.result;
      if (cursor && !claimed) {
        claimed = cursor.value;
        cursor.delete();
      }
    };
    transaction.oncomplete = () => resolve(claimed);
    transaction.onerror = () => reject(transaction.error);
  });
}

/**
 * Top the pool up to SLOT_TARGET for a drill. No-op offline, and failures are
 * swallowed: this runs opportunistically in the background and must never
 * interrupt what the athlete is doing.
 */
export async function topUp(drillKey, apiFn) {
  if (!navigator.onLine) return 0;
  try {
    const have = await countSlots(drillKey);
    const need = SLOT_TARGET - have;
    if (need <= 0) return 0;
    const res = await apiFn('/api/sessions/reserve', {
      method: 'POST',
      body: { drill_key: drillKey, count: need },
    });
    await putSlots(res.slots);
    return res.slots.length;
  } catch {
    return 0;
  }
}

// --------------------------------------------------------------- send queue

export async function enqueue(payload) {
  await tx(QUEUE, 'readwrite', (store) => store.put({ ...payload, queued_at: Date.now() }));
}

export async function pending() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const req = db.transaction(QUEUE, 'readonly').objectStore(QUEUE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

export async function pendingCount() {
  return (await pending()).length;
}

async function dequeue(sessionId) {
  await tx(QUEUE, 'readwrite', (store) => store.delete(sessionId));
}

/**
 * Try to deliver everything queued.
 *
 * A 4xx other than 401 means the server rejected the payload on its merits --
 * retrying forever would wedge the queue, so it is dropped. Network failures
 * leave the item queued for the next attempt.
 */
export async function flush(apiFn) {
  if (!navigator.onLine) return { sent: 0, failed: 0, results: [] };

  const items = await pending();
  let sent = 0;
  let failed = 0;
  const results = [];

  for (const item of items) {
    const { queued_at: _queuedAt, ...payload } = item;
    try {
      const result = await apiFn('/api/sessions/submit', { method: 'POST', body: payload });
      await dequeue(item.session_id);
      results.push(result);
      sent += 1;
    } catch (err) {
      if (err && err.permanent) {
        // The server will never accept this. Drop it rather than retrying on
        // every reconnect for the rest of time.
        await dequeue(item.session_id);
        failed += 1;
      } else {
        failed += 1;
      }
    }
  }
  return { sent, failed, results };
}

// --------------------------------------------------------------- utilities

export function onConnectivityChange(handler) {
  window.addEventListener('online', () => handler(true));
  window.addEventListener('offline', () => handler(false));
}

export async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return null;
  try {
    return await navigator.serviceWorker.register('sw.js', { scope: './' });
  } catch {
    return null;
  }
}

/** Convert a base64url VAPID key into the Uint8Array the Push API wants. */
export function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((ch) => ch.charCodeAt(0)));
}

/** Ask for notification permission and register a push subscription. */
export async function enablePush(apiFn) {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return { ok: false, reason: 'This browser cannot receive push notifications.' };
  }
  const { public_key: publicKey } = await apiFn('/api/notifications/vapid-key');
  if (!publicKey) {
    return { ok: false, reason: 'Push is not configured on this server yet.' };
  }
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    return { ok: false, reason: 'Notifications are blocked in your browser settings.' };
  }

  const registration = await navigator.serviceWorker.ready;
  const sub = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  });
  const json = sub.toJSON();
  await apiFn('/api/notifications/subscribe', {
    method: 'POST',
    body: { endpoint: sub.endpoint, p256dh: json.keys.p256dh, auth: json.keys.auth },
  });
  return { ok: true };
}
