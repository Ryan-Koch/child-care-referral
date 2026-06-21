/*
 * Compass provider-detail page behaviour.
 *
 * Three small, independent enhancements, each degrading to nothing if its markup
 * is absent:
 *   1. Tabs   - click a `.cd-tab[data-tab]` to reveal the matching
 *               `.cd-panel[data-panel]` (everything else hidden).
 *   2. Accordion - click a `.cd-insp__head` to expand/collapse its findings.
 *   3. Map    - plot a single marker from the #cd-map-point json_script block,
 *               mirroring the search map in compass_search.js.
 */
(function () {
  "use strict";

  var BUCKET_COLORS = { active: "#1F6E68", warn: "#DDA033", neutral: "#A89E91" };

  function initTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".cd-tab[data-tab]"));
    if (!tabs.length) {
      return;
    }
    var panels = document.querySelectorAll(".cd-panel[data-panel]");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var target = tab.getAttribute("data-tab");
        tabs.forEach(function (other) {
          other.classList.toggle("is-active", other === tab);
        });
        panels.forEach(function (panel) {
          panel.hidden = panel.getAttribute("data-panel") !== target;
        });
      });
    });
  }

  function initAccordion() {
    document.querySelectorAll(".cd-insp__head[data-toggle]").forEach(function (head) {
      head.addEventListener("click", function () {
        var card = head.closest(".cd-insp");
        if (card) {
          card.classList.toggle("is-open");
        }
      });
    });
  }

  function initBars() {
    // Quality-domain bar widths are data-driven, so set them here rather than
    // with an inline style attribute in the template.
    document.querySelectorAll(".cd-bar__fill[data-pct]").forEach(function (fill) {
      fill.style.width = fill.getAttribute("data-pct");
    });
  }

  function readPoint() {
    var dataEl = document.getElementById("cd-map-point");
    if (!dataEl) {
      return null;
    }
    try {
      return JSON.parse(dataEl.textContent);
    } catch (err) {
      return null;
    }
  }

  function initMap() {
    var mapEl = document.getElementById("cd-map");
    if (!mapEl || !window.L) {
      return;
    }
    var point = readPoint();
    if (!point) {
      return;
    }
    var map = L.map(mapEl, {
      zoomControl: false,
      attributionControl: false,
      scrollWheelZoom: false,
      dragging: false,
      doubleClickZoom: false,
    }).setView([point.lat, point.lng], 14);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
    }).addTo(map);
    L.circleMarker([point.lat, point.lng], {
      radius: 9,
      color: "#FFFFFF",
      weight: 3,
      fillColor: BUCKET_COLORS[point.bucket] || BUCKET_COLORS.neutral,
      fillOpacity: 1,
    }).addTo(map);
    setTimeout(function () {
      map.invalidateSize();
    }, 0);
  }

  function init() {
    initTabs();
    initAccordion();
    initBars();
    initMap();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
