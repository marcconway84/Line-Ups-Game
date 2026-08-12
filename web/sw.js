/* Service worker: makes the installed game work with no connection.
 *
 * Strategy matters here, and getting it wrong is invisible until an update ships:
 *
 *   The page itself is network-first. Ask the network, fall back to the cached
 *   copy only when offline. Serving the cached page first instead would show
 *   every returning player the *previous* version of the game, because the
 *   fresh copy only lands in the cache after the old one has already rendered.
 *
 *   Everything else - icons, the manifest - is cache-first. Those change rarely
 *   and are refreshed in the background when they do.
 *
 * The cache name is stamped with a hash of the built page by
 * scripts/build_standalone.py, so each release starts from a clean cache.
 */
var CACHE = "lineups-v1";
var PAGE = "./index.html";
var ASSETS = [
  "./",
  PAGE,
  "./manifest.webmanifest",
  "./icon.svg",
  "./icon-192.png",
  "./icon-512.png"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE)
      // Individual misses (an icon that failed to build) must not fail the install.
      .then(function (cache) {
        return Promise.all(ASSETS.map(function (url) {
          return cache.add(url).catch(function () { return null; });
        }));
      })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.filter(function (k) { return k !== CACHE; })
                               .map(function (k) { return caches.delete(k); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

function isPageRequest(request) {
  return request.mode === "navigate" ||
         (request.headers.get("accept") || "").indexOf("text/html") !== -1;
}

function cacheCopy(request, response) {
  if (response && response.status === 200 && response.type === "basic") {
    var copy = response.clone();
    caches.open(CACHE).then(function (cache) { cache.put(request, copy); });
  }
  return response;
}

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;

  if (isPageRequest(request)) {
    event.respondWith(
      fetch(request)
        .then(function (response) { return cacheCopy(request, response); })
        .catch(function () {
          // Offline: fall back to whatever copy of the game we have.
          return caches.match(request).then(function (hit) {
            return hit || caches.match(PAGE);
          });
        })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(function (hit) {
      var live = fetch(request)
        .then(function (response) { return cacheCopy(request, response); })
        .catch(function () { return hit; });
      return hit || live;
    })
  );
});
