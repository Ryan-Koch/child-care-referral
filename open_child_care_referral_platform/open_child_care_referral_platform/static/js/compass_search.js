/*
 * Compass provider-search map.
 *
 * Reads the current results page's points from the #compass-map-points
 * json_script block (emitted by the search layout from the view's `map_points`),
 * plots them on a Leaflet map with status-coloured markers, links each popup to
 * the provider detail page, and lightly syncs hover between a result card and its
 * marker. Degrades to nothing if Leaflet, the map element, or the data are
 * missing.
 */
(function () {
  "use strict";

  // Marker fill by status bucket (matches the card status-pill colours).
  var BUCKET_COLORS = { active: "#1F6E68", warn: "#DDA033", neutral: "#A89E91" };
  var HIGHLIGHT = "#CC6B4F";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[ch];
    });
  }

  function readPoints() {
    var dataEl = document.getElementById("compass-map-points");
    if (!dataEl) {
      return [];
    }
    try {
      return JSON.parse(dataEl.textContent) || [];
    } catch (err) {
      return [];
    }
  }

  function init() {
    if (!window.L) {
      return;
    }
    var mapEl = document.getElementById("compass-map");
    if (!mapEl) {
      return;
    }
    var points = readPoints();

    var map = L.map(mapEl, {
      zoomControl: true,
      attributionControl: false,
      scrollWheelZoom: true,
    });
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
    }).addTo(map);

    var markers = {};
    var bounds = [];
    points.forEach(function (point) {
      var base = BUCKET_COLORS[point.bucket] || BUCKET_COLORS.neutral;
      var marker = L.circleMarker([point.lat, point.lng], {
        radius: 8,
        color: "#FFFFFF",
        weight: 2.5,
        fillColor: base,
        fillOpacity: 1,
      });
      marker._cmpBase = base;
      marker.bindPopup(
        '<div style="font-weight:600;margin-bottom:4px;">' +
          escapeHtml(point.name) +
          '</div><a href="' +
          encodeURI(point.url) +
          '">View details</a>',
      );
      marker.addTo(map);
      markers[point.pk] = marker;
      bounds.push([point.lat, point.lng]);
    });

    if (bounds.length) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    } else {
      // No mappable providers on this page — show the continental US.
      map.setView([39.5, -98.35], 4);
    }
    // The pane may have been sized by CSS after init; recompute tiles.
    setTimeout(function () {
      map.invalidateSize();
    }, 0);

    function highlight(marker, on) {
      marker.setStyle({
        radius: on ? 12 : 8,
        weight: on ? 3 : 2.5,
        fillColor: on ? HIGHLIGHT : marker._cmpBase,
      });
      if (on) {
        marker.bringToFront();
      }
    }

    document.querySelectorAll("[data-provider-pk]").forEach(function (card) {
      var marker = markers[card.getAttribute("data-provider-pk")];
      if (!marker) {
        return;
      }
      card.addEventListener("mouseenter", function () {
        highlight(marker, true);
      });
      card.addEventListener("mouseleave", function () {
        highlight(marker, false);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
