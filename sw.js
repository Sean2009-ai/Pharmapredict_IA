// ── PharmaPredict IA — Service Worker ─────────────────────────
const CACHE_NAME    = 'pharmapredict-v1';
const CACHE_URLS    = [
  '/dashboard',
  '/static/sw.js',
];

// ── Install : mise en cache des ressources statiques ──────────
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(CACHE_URLS))
  );
});

// ── Activate : nettoyage des anciens caches ───────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── Fetch : stratégie Network First avec fallback cache ───────
self.addEventListener('fetch', event => {
  const { request } = event;

  // Ne pas intercepter les requêtes API (toujours réseau)
  if (request.url.includes('/api/')) return;

  // Requêtes GET uniquement
  if (request.method !== 'GET') return;

  event.respondWith(
    fetch(request)
      .then(response => {
        // Mettre en cache la réponse fraîche
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => {
        // Hors ligne → retourner le cache
        return caches.match(request).then(cached => {
          if (cached) return cached;
          // Fallback dashboard si page non cachée
          return caches.match('/dashboard');
        });
      })
  );
});

// ── Sync en arrière-plan : synchroniser les données offline ───
self.addEventListener('sync', event => {
  if (event.tag === 'sync-stock') {
    event.waitUntil(syncPendingData());
  }
});

async function syncPendingData() {
  // Récupérer les données en attente depuis IndexedDB
  const pending = await getPendingFromIDB();
  for (const item of pending) {
    try {
      await fetch('/api/upload', { method: 'POST', body: item.formData });
      await removePendingFromIDB(item.id);
    } catch (e) {
      console.warn('[SW] Sync échoué, retry plus tard', e);
    }
  }
}

// Stubs IndexedDB (à implémenter si besoin offline avancé)
async function getPendingFromIDB()       { return []; }
async function removePendingFromIDB(id) { return; }
