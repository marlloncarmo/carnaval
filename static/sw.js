const CACHE_NAME = 'carnaval-bh-v9';
const URLS_TO_CACHE = [
    '/',
    '/static/style.css',
    '/static/manifest.json',
    '/static/images/carnaval-mask-icon.png',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
    'https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap'
];

// 1. INSTALAÇÃO: Cacheia os arquivos e força a ativação imediata (skipWaiting)
self.addEventListener('install', event => {
    console.log('[SW] Instalando versão:', CACHE_NAME);
    
    // Força o SW a pular a fase de "espera" e ativar imediatamente
    self.skipWaiting();

    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                return cache.addAll(URLS_TO_CACHE);
            })
    );
});

// 2. ATIVAÇÃO: Limpa caches antigos e assume o controle das abas (clients.claim)
self.addEventListener('activate', event => {
    console.log('[SW] Ativando e limpando caches antigos...');
    
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cache => {
                    // Se o cache não for o atual (v3), apaga!
                    if (cache !== CACHE_NAME) {
                        console.log('[SW] Apagando cache antigo:', cache);
                        return caches.delete(cache);
                    }
                })
            );
        }).then(() => {
            // Diz ao SW para controlar todas as abas abertas imediatamente
            return self.clients.claim();
        })
    );
});

// 3. FETCH: Estratégia Híbrida
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Estratégia A: HTML e JSON (Dados) -> Network First (Tenta rede, se falhar vai pro cache)
    // Isso garante que o usuário sempre veja a versão mais nova se tiver internet.
    if (event.request.mode === 'navigate' || url.pathname.endsWith('.json') || url.pathname === '/') {
        event.respondWith(
            fetch(event.request)
                .then(networkResponse => {
                    return caches.open(CACHE_NAME).then(cache => {
                        cache.put(event.request, networkResponse.clone());
                        return networkResponse;
                    });
                })
                .catch(() => {
                    return caches.match(event.request);
                })
        );
    } 
    // Estratégia B: Imagens, CSS, JS e Libs Externas -> Cache First (Rápido)
    else {
        event.respondWith(
            caches.match(event.request)
                .then(cachedResponse => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    return fetch(event.request);
                })
        );
    }
});