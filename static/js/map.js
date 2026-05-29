/* Map view — in-trip map and lifetime map. Single module, factory style.
 *
 * Read the design spec at docs/superpowers/specs/2026-05-29-map-view-design.md
 * before editing.
 */

(function () {
  "use strict";

  function getMapboxToken() {
    var meta = document.querySelector('meta[name="mapbox-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function getContainer() {
    return document.getElementById("vp-trip-map") || document.getElementById("vp-lifetime-map");
  }

  // ───────────────────────────── in-trip map ────────────────────────

  window.vpInitTripMap = function () {
    var el = document.getElementById("vp-trip-map");
    if (!el || typeof mapboxgl === "undefined") return;
    var token = getMapboxToken();
    if (!token) return;

    mapboxgl.accessToken = token;

    var map = new mapboxgl.Map({
      container: el,
      style: "mapbox://styles/mapbox/streets-v12",
      center: [0, 20],
      zoom: 1,
    });

    map.addControl(new mapboxgl.NavigationControl(), "top-right");

    map.on("load", function () {
      fetch(el.getAttribute("data-geojson-url"))
        .then(function (r) { return r.json(); })
        .then(function (geojson) {
          renderTripPins(map, geojson);
          updateSideNote(geojson);
        })
        .catch(function (err) {
          console.error("Failed to load map data:", err);
        });
    });
  };

  function renderTripPins(map, geojson) {
    map.addSource("vp-pins", { type: "geojson", data: geojson });

    map.addLayer({
      id: "vp-pins-layer",
      type: "circle",
      source: "vp-pins",
      paint: {
        "circle-radius": 7,
        "circle-color": ["get", "color"],
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
      },
    });

    if (geojson.features && geojson.features.length > 0) {
      var bounds = new mapboxgl.LngLatBounds();
      geojson.features.forEach(function (f) {
        bounds.extend(f.geometry.coordinates);
      });
      map.fitBounds(bounds, { padding: 40, maxZoom: 12, duration: 0 });
    }
  }

  function updateSideNote(geojson) {
    /* For now just hide the side note — Task 7 will compute the
     * no-location count from a separate endpoint or pass it in
     * via the page template. */
  }
})();
