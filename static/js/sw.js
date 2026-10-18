/* 아파요 서비스 워커: 오프라인 안내 페이지와 푸시 알림 */
const CACHE = 'sicklog-v5';
const OFFLINE_URL = '/offline/';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add(OFFLINE_URL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;

  // 화면은 항상 최신 기록을 보여야 하므로 네트워크 우선, 끊겼을 때만 오프라인 안내
  if (request.mode === 'navigate') {
    // 화면을 깨운 직후처럼 잠깐 끊긴 경우가 많아서, 한 번 더 시도한 뒤에만 오프라인 안내를 보여 준다
    event.respondWith(
      fetch(request)
        .catch(() => new Promise(r => setTimeout(r, 1200)).then(() => fetch(request)))
        .catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }
  // 정적 파일은 해시가 붙어 있어 캐시 우선
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(hit => hit || fetch(request).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(request, copy)); }
        return res;
      }))
    );
  }
});

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || '아파요', {
    body: data.body || '',
    tag: data.tag || 'sicklog',
    renotify: true,
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/badge-96.png',  // 안드로이드 상태바: 투명 배경의 흰 실루엣이어야 한다
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(event.notification.data.url || '/', location.origin).href;
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    const open = list.find(c => c.url.startsWith(location.origin));
    if (open) { open.navigate(target); return open.focus(); }
    return clients.openWindow(target);
  }));
});
