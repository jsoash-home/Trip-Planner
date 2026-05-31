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
          wireDayChips(map);
          wireDrag(map, el.getAttribute("data-trip-id"), userCanEdit());
        })
        .catch(function (err) {
          console.error("Failed to load map data:", err);
        });
    });
  };

  // ───────────────────────────── mini-map teaser ────────────────────

  window.vpInitMiniMap = function () {
    var el = document.getElementById("vp-mini-map");
    if (!el || typeof mapboxgl === "undefined") return;
    var token = getMapboxToken();
    if (!token) return;

    mapboxgl.accessToken = token;

    var map = new mapboxgl.Map({
      container: el,
      style: "mapbox://styles/mapbox/streets-v12",
      center: [0, 20],
      zoom: 1,
      interactive: false,
      attributionControl: false,
    });

    map.on("load", function () {
      fetch(el.getAttribute("data-geojson-url"))
        .then(function (r) { return r.json(); })
        .then(function (geojson) {
          if (!geojson.features.length) return;
          map.addSource("vp-mini-pins", { type: "geojson", data: geojson });
          map.addLayer({
            id: "vp-mini-pins-layer",
            type: "circle",
            source: "vp-mini-pins",
            paint: {
              "circle-radius": 5,
              "circle-color": ["get", "color"],
              "circle-stroke-width": 1.5,
              "circle-stroke-color": "#ffffff",
            },
          });
          var bounds = new mapboxgl.LngLatBounds();
          geojson.features.forEach(function (f) {
            bounds.extend(f.geometry.coordinates);
          });
          map.fitBounds(bounds, { padding: 20, maxZoom: 11, duration: 0 });
        })
        .catch(function (err) { console.error("Mini-map fetch:", err); });
    });
  };

  // ───────────────────────────── lifetime map ───────────────────────

  window.vpInitLifetimeMap = function () {
    var el = document.getElementById("vp-lifetime-map");
    if (!el || typeof mapboxgl === "undefined") return;
    var token = getMapboxToken();
    if (!token) return;

    mapboxgl.accessToken = token;

    var map = new mapboxgl.Map({
      container: el,
      style: "mapbox://styles/mapbox/streets-v12",
      center: [0, 20],
      zoom: 1.2,
    });

    map.addControl(new mapboxgl.NavigationControl(), "top-right");

    map.on("load", function () {
      fetch(el.getAttribute("data-geojson-url"))
        .then(function (r) { return r.json(); })
        .then(function (geojson) {
          renderLifetimePins(map, geojson);
          renderStatsBar(geojson);
          renderYearChips(map, geojson);
          fitToFeatures(map, geojson);
        })
        .catch(function (err) { console.error("Lifetime map fetch:", err); });
    });
  };

  function renderLifetimePins(map, geojson) {
    map.addSource("vp-pins", {
      type: "geojson",
      data: geojson,
      cluster: true,
      clusterMaxZoom: 9,
      clusterRadius: 50,
    });

    // Unclustered pins (visible at zoom > clusterMaxZoom).
    map.addLayer({
      id: "vp-pins-layer",
      type: "circle",
      source: "vp-pins",
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-radius": 5,
        "circle-color": ["get", "color"],
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#ffffff",
      },
    });

    // Cluster circles (visible at world / country zoom).
    map.addLayer({
      id: "vp-clusters-layer",
      type: "circle",
      source: "vp-pins",
      filter: ["has", "point_count"],
      paint: {
        "circle-color": "#4a6fa5",
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
        "circle-radius": [
          "step", ["get", "point_count"],
          12, 10,
          18, 30,
          24,
        ],
      },
    });

    map.addLayer({
      id: "vp-cluster-counts",
      type: "symbol",
      source: "vp-pins",
      filter: ["has", "point_count"],
      layout: {
        "text-field": ["get", "point_count_abbreviated"],
        "text-size": 12,
      },
      paint: { "text-color": "#ffffff" },
    });

    // Click a cluster ⇒ zoom in.
    map.on("click", "vp-clusters-layer", function (e) {
      var cluster = e.features[0];
      var clusterId = cluster.properties.cluster_id;
      map.getSource("vp-pins").getClusterExpansionZoom(clusterId, function (err, zoom) {
        if (err) return;
        map.easeTo({ center: cluster.geometry.coordinates, zoom: zoom });
      });
    });
    map.on("mouseenter", "vp-clusters-layer", function () { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "vp-clusters-layer", function () { map.getCanvas().style.cursor = ""; });

    // Click an unclustered pin ⇒ popup.
    map.on("click", "vp-pins-layer", function (e) {
      var f = e.features[0];
      new mapboxgl.Popup({ offset: 10, className: "vp-map-popup" })
        .setLngLat(f.geometry.coordinates)
        .setHTML(buildPopupHTML(f.properties, /*lifetimeView=*/ true))
        .addTo(map);
    });
    map.on("mouseenter", "vp-pins-layer", function () { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "vp-pins-layer", function () { map.getCanvas().style.cursor = ""; });

    // Country paint at world zoom — Mapbox's built-in boundaries tileset
    // shaded for every country the user has visited. Fades out past zoom 4
    // so the cluster + pin layers take over.
    var visited = (geojson.meta && geojson.meta.visited_country_codes) || [];

    map.addSource("vp-country-bounds", {
      type: "vector",
      url: "mapbox://mapbox.country-boundaries-v1",
    });

    var matchExpr = ["match", ["get", "iso_3166_1"]];
    if (visited.length === 0) {
      // Mapbox match requires at least one case. Use a sentinel that won't match.
      matchExpr.push("__NONE__", "rgba(74,111,165,0.25)");
    } else {
      visited.forEach(function (code) {
        matchExpr.push(code, "rgba(74,111,165,0.25)");
      });
    }
    matchExpr.push("rgba(0,0,0,0)");

    map.addLayer({
      id: "vp-country-paint",
      source: "vp-country-bounds",
      "source-layer": "country_boundaries",
      type: "fill",
      maxzoom: 4,
      paint: {
        "fill-color": matchExpr,
        "fill-outline-color": "rgba(0,0,0,0)",
      },
    }, "vp-clusters-layer");
  }

  function fitToFeatures(map, geojson) {
    if (!geojson.features.length) return;
    var bounds = new mapboxgl.LngLatBounds();
    geojson.features.forEach(function (f) {
      bounds.extend(f.geometry.coordinates);
    });
    map.fitBounds(bounds, { padding: 50, maxZoom: 6, duration: 0 });
  }

  // Stubs — populated in Task 15.
  function renderStatsBar(geojson) {}
  function renderYearChips(map, geojson) {}

  function userCanEdit() {
    var el = getContainer();
    return el && el.getAttribute("data-can-edit") === "true";
  }

  function wireDrag(map, tripId, canEdit) {
    if (!canEdit) return;

    var dragging = null;

    map.on("mouseenter", "vp-pins-layer", function () {
      map.getCanvas().style.cursor = "grab";
    });
    map.on("mousedown", "vp-pins-layer", function (e) {
      e.preventDefault();
      dragging = e.features[0];
      map.getCanvas().style.cursor = "grabbing";
      map.dragPan.disable();
    });
    map.on("mousemove", function (e) {
      if (!dragging) return;
      var src = map.getSource("vp-pins");
      var data = src._data;
      var feat = data.features.find(function (f) {
        return f.properties.row_type === dragging.properties.row_type &&
               f.properties.row_id === dragging.properties.row_id;
      });
      if (feat) {
        feat.geometry.coordinates = [e.lngLat.lng, e.lngLat.lat];
        src.setData(data);
      }
    });
    map.on("mouseup", function (e) {
      if (!dragging) return;
      var coords = { lat: e.lngLat.lat, lng: e.lngLat.lng };
      var p = dragging.properties;
      dragging = null;
      map.getCanvas().style.cursor = "";
      map.dragPan.enable();

      fetch("/trips/" + tripId + "/map/pin/" + p.row_type + "/" + p.row_id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(coords),
      }).then(function (r) {
        if (r.status === 204) showToast("Pin saved");
        else showToast("Could not save — try again");
      }).catch(function () { showToast("Could not save — try again"); });
    });
  }

  function showToast(msg) {
    var t = document.createElement("div");
    t.className = "vp-map-toast";
    t.textContent = msg;
    Object.assign(t.style, {
      position: "fixed", bottom: "20px", left: "50%",
      transform: "translateX(-50%)",
      background: "rgba(0,0,0,0.85)", color: "white",
      padding: "8px 14px", borderRadius: "6px",
      fontSize: "0.9rem", zIndex: 9999,
    });
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 1500);
  }

  function wireDayChips(map) {
    var chips = document.querySelectorAll(".vp-day-chip-bar .vp-day-chip");
    if (!chips.length) return;

    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        chips.forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
        chip.setAttribute("aria-pressed", "true");
        applyDayFilter(map, chip.getAttribute("data-day"));
      });
    });
  }

  function applyDayFilter(map, day) {
    if (!map.getLayer("vp-pins-layer")) return;

    if (day === "all") {
      map.setFilter("vp-pins-layer", null);
    } else if (day === "anytime") {
      map.setFilter("vp-pins-layer", ["==", ["get", "day_index"], null]);
    } else {
      var idx = parseInt(day, 10);
      map.setFilter("vp-pins-layer", ["==", ["get", "day_index"], idx]);
    }

    var features = map.querySourceFeatures("vp-pins");
    if (!features.length) return;
    var bounds = new mapboxgl.LngLatBounds();
    features.forEach(function (f) {
      if (matchesCurrentFilter(map, f)) {
        bounds.extend(f.geometry.coordinates);
      }
    });
    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 40, maxZoom: 14, duration: 400 });
    }
  }

  function matchesCurrentFilter(map, feature) {
    return true;
  }

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
