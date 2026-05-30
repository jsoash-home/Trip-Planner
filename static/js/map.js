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

    map.on("click", "vp-pins-layer", function (e) {
      var f = e.features[0];
      var p = f.properties;
      new mapboxgl.Popup({ offset: 12, className: "vp-map-popup" })
        .setLngLat(f.geometry.coordinates)
        .setHTML(buildPopupHTML(p, /*lifetimeView=*/ false))
        .addTo(map);
    });

    map.on("mouseenter", "vp-pins-layer", function () { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "vp-pins-layer", function () { map.getCanvas().style.cursor = ""; });

    if (geojson.features && geojson.features.length > 0) {
      var bounds = new mapboxgl.LngLatBounds();
      geojson.features.forEach(function (f) {
        bounds.extend(f.geometry.coordinates);
      });
      map.fitBounds(bounds, { padding: 40, maxZoom: 12, duration: 0 });
    }
  }

  function buildPopupHTML(p, lifetimeView) {
    var safe = function (s) {
      if (s === null || s === undefined) return "";
      var d = document.createElement("div");
      d.textContent = String(s);
      return d.innerHTML;
    };

    var dt = "";
    if (p.datetime_iso) {
      try {
        var dObj = new Date(p.datetime_iso);
        dt = dObj.toLocaleString(undefined, {
          weekday: "short", month: "short", day: "numeric",
          hour: "numeric", minute: "2-digit",
        });
      } catch (e) { /* leave blank */ }
    }

    var link, label;
    if (lifetimeView) {
      link = "/trips/" + p.trip_id;
      label = "Open trip →";
    } else if (p.row_type === "booking") {
      link = "/trips/" + p.trip_id + "/bookings/" + p.row_id + "/edit";
      label = "Open booking →";
    } else {
      link = "/trips/" + p.trip_id + "/itinerary/" + p.row_id + "/edit";
      label = "Open itinerary item →";
    }

    return (
      '<div class="vp-popup-title">' + safe(p.title) + '</div>' +
      (dt ? '<div class="vp-popup-meta">' + safe(dt) + '</div>' : '') +
      (p.location_text ? '<div class="vp-popup-meta">' + safe(p.location_text) + '</div>' : '') +
      '<a class="vp-popup-link" href="' + link + '">' + label + '</a>'
    );
  }
})();
