(function () {
  "use strict";

  var DEFAULT_CONTAINER_ID = "map-container";
  var DEFAULT_CENTER = [121.4737, 31.2304];
  var DEFAULT_ZOOM = 12;
  var ROUTE_REQUEST_DELAY_MS = 380;
  var state = {
    map: null,
    containerId: null,
    overlays: [],
    routeServices: [],
    infoWindow: null,
    latestPayload: null,
    renderToken: 0,
    routeStats: null,
    routeCache: {},
    routeQueue: Promise.resolve(),
    lastOptions: {},
    legendTarget: null,
    listTarget: null,
    statusTarget: null,
    togglesTarget: null
  };

  function setStatus(message, isError) {
    if (!state.statusTarget) {
      if (message) {
        (isError ? console.error : console.info)("[renderTravelMap] " + message);
      }
      return;
    }

    state.statusTarget.textContent = message || "";
    state.statusTarget.style.background = isError
      ? "rgba(239, 68, 68, 0.12)"
      : "rgba(2, 132, 199, 0.08)";
    state.statusTarget.style.color = isError ? "#991b1b" : "#0c4a6e";
  }

  function resetRouteStats() {
    state.routeStats = {
      total: 0,
      success: 0,
      fallback: 0,
      rerouted: 0,
      failures: []
    };
  }

  function recordRouteSuccess() {
    if (state.routeStats) {
      state.routeStats.success += 1;
    }
  }

  function scheduleRouteRequest(task) {
    state.routeQueue = state.routeQueue
      .catch(function () {
        return undefined;
      })
      .then(function () {
        return new Promise(function (resolve) {
          window.setTimeout(resolve, ROUTE_REQUEST_DELAY_MS);
        });
      })
      .then(task);

    return state.routeQueue;
  }

  function routeCacheKey(leg, mode, options) {
    return [
      mode,
      options.city || "",
      options.transitCity || "",
      options.transitCityDestination || "",
      leg.from_lon,
      leg.from_lat,
      leg.to_lon,
      leg.to_lat
    ].join("|");
  }

  function getCachedRoute(leg, mode, options) {
    return state.routeCache[routeCacheKey(leg, mode, options)];
  }

  function setCachedRoute(leg, mode, options, path) {
    if (Array.isArray(path) && path.length > 1) {
      state.routeCache[routeCacheKey(leg, mode, options)] = path;
    }
  }

  function recordRouteFallback(leg, reason) {
    if (!state.routeStats) {
      return;
    }
    state.routeStats.fallback += 1;
    if (state.routeStats.failures.length < 4) {
      state.routeStats.failures.push(
        (leg.from_poi || "unknown") +
          " -> " +
          (leg.to_poi || "unknown") +
          ": " +
          (reason || "route service failed")
      );
    }
  }

  function recordRouteReroute(leg, reason) {
    if (!state.routeStats) {
      return;
    }
    state.routeStats.rerouted += 1;
    if (state.routeStats.failures.length < 4) {
      state.routeStats.failures.push(
        (leg.from_poi || "unknown") +
          " -> " +
          (leg.to_poi || "unknown") +
          ": " +
          (reason || "fallback to walking")
      );
    }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function isFiniteNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function isValidCoord(lat, lon) {
    return isFiniteNumber(lat) && isFiniteNumber(lon) && !(lat === 0 && lon === 0);
  }

  function toLngLat(point) {
    return new AMap.LngLat(point.lon, point.lat);
  }

  function resolveTarget(selector) {
    if (!selector) {
      return null;
    }
    return document.querySelector(selector);
  }

  function initMap(containerId) {
    if (!window.AMap) {
      throw new Error("AMap JS SDK is not loaded.");
    }

    var container = document.getElementById(containerId);
    if (!container) {
      throw new Error('Map container "' + containerId + '" was not found.');
    }

    if (state.map && state.containerId === containerId) {
      return state.map;
    }

    if (state.map && state.containerId !== containerId) {
      state.map.destroy();
      state.map = null;
    }

    state.map = new AMap.Map(containerId, {
      zoom: DEFAULT_ZOOM,
      center: DEFAULT_CENTER,
      resizeEnable: true,
      mapStyle: "amap://styles/whitesmoke",
      viewMode: "2D"
    });
    state.containerId = containerId;
    state.infoWindow = new AMap.InfoWindow({
      offset: new AMap.Pixel(0, -26),
      closeWhenClickMap: true
    });

    AMap.plugin(["AMap.Scale", "AMap.ToolBar"], function () {
      state.map.addControl(new AMap.Scale());
      state.map.addControl(
        new AMap.ToolBar({
          position: { top: "18px", right: "18px" }
        })
      );
    });

    return state.map;
  }

  function clearMap() {
    if (!state.map) {
      return;
    }

    state.routeServices.forEach(function (service) {
      if (service && typeof service.clear === "function") {
        service.clear();
      }
    });

    state.routeServices = [];

    if (state.overlays.length) {
      state.map.remove(state.overlays);
    }

    state.overlays = [];

    if (state.infoWindow) {
      state.infoWindow.close();
    }
  }

  function collectDisplayDays(payload, focusDay) {
    var days = Array.isArray(payload && payload.days) ? payload.days : [];
    if (!focusDay || focusDay === "all") {
      return days;
    }

    return days.filter(function (day) {
      return String(day.day_index) === String(focusDay);
    });
  }

  function renderLegend(days) {
    if (!state.legendTarget) {
      return;
    }

    if (!days.length) {
      state.legendTarget.innerHTML = '<div class="empty-state">当前没有可显示的路线。</div>';
      return;
    }

    state.legendTarget.innerHTML = days
      .map(function (day) {
        return [
          '<div class="legend-item">',
          '  <span class="legend-swatch" style="background:' + escapeHtml(day.color || "#0EA5E9") + ';"></span>',
          "  <div>",
          '    <div class="legend-name">Day ' + escapeHtml(day.day_index) + " · " + escapeHtml(day.theme || "未命名主题") + "</div>",
          '    <div class="legend-meta">' +
            escapeHtml(day.area || "未知区域") +
            " · " +
            escapeHtml((day.stops || []).length) +
            " stops · " +
            escapeHtml(day.inter_stop_duration_min || 0) +
            " min</div>",
          "  </div>",
          "</div>"
        ].join("");
      })
      .join("");
  }

  function renderDayCards(days) {
    if (!state.listTarget) {
      return;
    }

    if (!days.length) {
      state.listTarget.innerHTML = '<div class="empty-state">没有可展示的每日行程。</div>';
      return;
    }

    state.listTarget.innerHTML = days
      .map(function (day) {
        return [
          '<div class="day-card" style="--day-color:' + escapeHtml(day.color || "#0EA5E9") + ';">',
          '  <div class="day-title-row">',
          '    <div class="day-title">Day ' + escapeHtml(day.day_index) + " · " + escapeHtml(day.theme || "未命名主题") + "</div>",
          '    <span class="day-chip">' + escapeHtml(day.area || "Unknown") + "</span>",
          "  </div>",
          '  <div class="day-meta">节点 ' +
            escapeHtml((day.stops || []).length) +
            " 个 · 距离 " +
            escapeHtml(day.inter_stop_distance_m || 0) +
            " m · 用时 " +
            escapeHtml(day.inter_stop_duration_min || 0) +
            " min</div>",
          '  <div class="day-meta">' +
            escapeHtml(
              (day.stops || [])
                .map(function (stop) {
                  return stop.sequence + ". " + stop.poi_name;
                })
                .join(" → ")
            ) +
            "</div>",
          "</div>"
        ].join("");
      })
      .join("");
  }

  function buildRenderOptions(options, overrides) {
    var merged = {};
    Object.keys(options || {}).forEach(function (key) {
      merged[key] = options[key];
    });
    Object.keys(overrides || {}).forEach(function (key) {
      merged[key] = overrides[key];
    });
    return merged;
  }

  function renderToggles(payload, options) {
    if (!state.togglesTarget) {
      return;
    }

    var days = Array.isArray(payload && payload.days) ? payload.days : [];
    var currentFocus = options && options.focusDay ? String(options.focusDay) : "all";

    var buttons = [
      '<button class="view-toggle' + (currentFocus === "all" ? " is-active" : "") + '" data-day="all">All Days</button>'
    ];

    days.forEach(function (day) {
      var dayValue = String(day.day_index);
      buttons.push(
        '<button class="view-toggle' +
          (currentFocus === dayValue ? " is-active" : "") +
          '" data-day="' +
          escapeHtml(dayValue) +
          '">Day ' +
          escapeHtml(dayValue) +
          "</button>"
      );
    });

    state.togglesTarget.innerHTML = buttons.join("");

    Array.prototype.forEach.call(
      state.togglesTarget.querySelectorAll(".view-toggle"),
      function (button) {
        button.addEventListener("click", function () {
          window.renderTravelMap(payload, buildRenderOptions(options, {
            focusDay: this.getAttribute("data-day"),
          }));
        });
      }
    );
  }

  function renderModeControls(payload, options) {
    var target = resolveTarget(options.modeSelector || "#route-mode-controls");
    if (!target) {
      return;
    }

    var currentMode = options.routeModeOverride || "auto";
    var modes = [
      ["auto", "跟随行程"],
      ["walking", "步行预览"],
      ["driving", "驾车预览"],
      ["transit", "公交/地铁预览"]
    ];

    target.innerHTML = modes
      .map(function (entry) {
        return (
          '<button class="view-toggle' +
          (currentMode === entry[0] ? " is-active" : "") +
          '" data-route-mode="' +
          entry[0] +
          '">' +
          entry[1] +
          "</button>"
        );
      })
      .join("");

    Array.prototype.forEach.call(
      target.querySelectorAll(".view-toggle"),
      function (button) {
        button.addEventListener("click", function () {
          var nextMode = this.getAttribute("data-route-mode");
          window.renderTravelMap(payload, buildRenderOptions(options, {
            routeModeOverride: nextMode === "auto" ? null : nextMode
          }));
        });
      }
    );
  }

  function validatePayload(payload) {
    if (!payload || typeof payload !== "object") {
      throw new Error("mapPayload is empty or invalid.");
    }

    if (!Array.isArray(payload.days)) {
      throw new Error("mapPayload.days is required and must be an array.");
    }
  }

  function buildPopupHtml(day, stop) {
    return [
      '<div class="map-popup">',
      "  <h3>" + escapeHtml(stop.sequence) + ". " + escapeHtml(stop.poi_name || "Unnamed POI") + "</h3>",
      '  <div class="popup-subtitle">Day ' +
        escapeHtml(day.day_index) +
        " · " +
        escapeHtml(day.theme || "未命名主题") +
        " · " +
        escapeHtml(stop.time_slot || "unknown") +
        "</div>",
      '  <div class="popup-line"><strong>Category:</strong> ' + escapeHtml(stop.category || "-") + "</div>",
      '  <div class="popup-line"><strong>District:</strong> ' + escapeHtml(stop.district || "-") + "</div>",
      '  <div class="popup-line"><strong>Address:</strong> ' + escapeHtml(stop.address || "-") + "</div>",
      '  <div class="popup-line"><strong>Hours:</strong> ' + escapeHtml(stop.open_hours || "-") + "</div>",
      '  <div class="popup-line"><strong>Ticket:</strong> ' + escapeHtml(stop.ticket_price == null ? "-" : stop.ticket_price) + "</div>",
      '  <div class="popup-line"><strong>Arrival:</strong> ' +
        escapeHtml(stop.arrival_mode || "-") +
        " · " +
        escapeHtml(stop.arrival_duration_min == null ? "-" : stop.arrival_duration_min + " min") +
        "</div>",
      '  <div class="popup-line"><strong>Hint:</strong> ' + escapeHtml(stop.transport_hint || "-") + "</div>",
      "</div>"
    ].join("");
  }

  function addOverlay(overlay, token) {
    if (!overlay) {
      return;
    }

    if (token != null && token !== state.renderToken) {
      return;
    }

    state.overlays.push(overlay);
    if (state.map) {
      state.map.add(overlay);
    }
  }

  function createMarker(day, stop, token) {
    var content =
      '<div class="map-marker" style="background:' +
      escapeHtml(day.color || "#0EA5E9") +
      ';">' +
      escapeHtml(stop.sequence) +
      "</div>";

    var marker = new AMap.Marker({
      position: [stop.lon, stop.lat],
      anchor: "bottom-center",
      offset: new AMap.Pixel(0, 0),
      content: content,
      title: stop.poi_name || ""
    });

    marker.on("click", function () {
      if (state.infoWindow) {
        state.infoWindow.setContent(buildPopupHtml(day, stop));
        state.infoWindow.open(state.map, marker.getPosition());
      }
    });

    addOverlay(marker, token);
  }

  function renderStops(days, token) {
    days.forEach(function (day) {
      (day.stops || []).forEach(function (stop) {
        if (!isValidCoord(stop.lat, stop.lon)) {
          return;
        }
        createMarker(day, stop, token);
      });
    });
  }

  function flattenPath(routeResult) {
    var routes = routeResult && routeResult.routes;
    if (!Array.isArray(routes) || !routes.length) {
      return [];
    }

    var steps = routes[0].steps || [];
    var path = [];
    steps.forEach(function (step) {
      appendPointList(path, step.path);
      appendPointList(path, step.polyline);
    });

    return path;
  }

  function addFallbackPolyline(leg, color, token) {
    var polyline = new AMap.Polyline({
      path: [
        [leg.from_lon, leg.from_lat],
        [leg.to_lon, leg.to_lat]
      ],
      strokeColor: color,
      strokeWeight: 5,
      strokeOpacity: 0.7,
      strokeStyle: "dashed",
      lineJoin: "round"
    });
    addOverlay(polyline, token);
  }

  function addRoutePolyline(path, color, mode, token) {
    var polyline = new AMap.Polyline({
      path: path,
      strokeColor: color,
      strokeWeight: mode === "walking" ? 5 : mode === "transit" ? 7 : 6,
      strokeOpacity: 0.92,
      strokeStyle: mode === "walking" ? "dashed" : "solid",
      lineCap: "round",
      lineJoin: "round",
      showDir: mode !== "walking"
    });
    addOverlay(polyline, token);
  }

  function describeRouteFailure(status, result) {
    if (typeof result === "string") {
      return status + " / " + result;
    }
    if (result && result.info) {
      return status + " / " + result.info;
    }
    if (result && result.infocode) {
      return status + " / infocode=" + result.infocode;
    }
    if (result && result.message) {
      return status + " / " + result.message;
    }
    if (result && result.infoCode) {
      return status + " / infoCode=" + result.infoCode;
    }
    return status || "unknown";
  }

  function requestWalkingFallbackPath(leg, color, token, reason) {
    return new Promise(function (resolve) {
      if (!AMap.Walking) {
        recordRouteFallback(leg, reason + "; AMap.Walking unavailable");
        addFallbackPolyline(leg, color, token);
        resolve();
        return;
      }

      var cachedPath = getCachedRoute(leg, "walking", {});
      if (cachedPath) {
        addRoutePolyline(cachedPath, color, "walking", token);
        recordRouteSuccess();
        recordRouteReroute(leg, "公交/地铁不可用，已复用步行缓存路线；" + reason);
        resolve();
        return;
      }

      scheduleRouteRequest(function () {
        if (token !== state.renderToken) {
          resolve();
          return;
        }

        var walking = new AMap.Walking({
          hideMarkers: true,
          autoFitView: false
        });
        state.routeServices.push(walking);

        walking.search(
          [leg.from_lon, leg.from_lat],
          [leg.to_lon, leg.to_lat],
          function (status, result) {
            if (token !== state.renderToken) {
              resolve();
              return;
            }

            if (status === "complete") {
              var path = flattenPath(result);
              if (path.length > 1) {
                setCachedRoute(leg, "walking", {}, path);
                addRoutePolyline(path, color, "walking", token);
                recordRouteSuccess();
                recordRouteReroute(leg, "公交/地铁不可用，已改用步行路线；" + reason);
                resolve();
                return;
              }
            }

            recordRouteFallback(
              leg,
              "公交/地铁不可用，步行兜底也失败；" + reason + "; walking=" + describeRouteFailure(status, result)
            );
            addFallbackPolyline(leg, color, token);
            resolve();
          }
        );
      });
    });
  }

  function getEffectiveMode(leg, options) {
    var override = options && options.routeModeOverride;
    if (override === "walking" || override === "driving" || override === "transit") {
      return override;
    }
    if (leg.mode === "walking" || leg.mode === "driving" || leg.mode === "transit") {
      return leg.mode;
    }
    return "driving";
  }

  function requestLegPath(leg, color, token, options) {
    return new Promise(function (resolve) {
      if (!isValidCoord(leg.from_lat, leg.from_lon) || !isValidCoord(leg.to_lat, leg.to_lon)) {
        recordRouteFallback(leg, "invalid coordinates");
        resolve();
        return;
      }

      var mode = getEffectiveMode(leg, options);
      var service;
      var cachedPath = getCachedRoute(leg, mode, options);
      if (cachedPath) {
        addRoutePolyline(cachedPath, color, mode, token);
        recordRouteSuccess();
        resolve();
        return;
      }

      if (mode === "walking") {
        scheduleRouteRequest(function () {
          if (token !== state.renderToken) {
            resolve();
            return;
          }
          service = new AMap.Walking({
            hideMarkers: true,
            autoFitView: false
          });
          state.routeServices.push(service);
          service.search(
            [leg.from_lon, leg.from_lat],
            [leg.to_lon, leg.to_lat],
            function (status, result) {
              if (token !== state.renderToken) {
                resolve();
                return;
              }
              if (status === "complete") {
                var path = flattenPath(result);
                if (path.length > 1) {
                  setCachedRoute(leg, mode, options, path);
                  addRoutePolyline(path, color, mode, token);
                  recordRouteSuccess();
                } else {
                  recordRouteFallback(leg, "empty walking path");
                  addFallbackPolyline(leg, color, token);
                }
              } else {
                recordRouteFallback(leg, describeRouteFailure(status, result));
                addFallbackPolyline(leg, color, token);
              }
              resolve();
            }
          );
        });
      } else if (mode === "transit") {
        if (!AMap.Transfer) {
          requestWalkingFallbackPath(leg, color, token, "AMap.Transfer plugin is unavailable").then(resolve);
          return;
        }

        scheduleRouteRequest(function () {
          if (token !== state.renderToken) {
            resolve();
            return;
          }
          service = new AMap.Transfer({
            city: options.transitCity || options.city || "",
            cityd: options.transitCityDestination || options.city || "",
            policy: AMap.TransferPolicy ? AMap.TransferPolicy.LEAST_TIME : undefined
          });
          state.routeServices.push(service);
          service.search(
            new AMap.LngLat(leg.from_lon, leg.from_lat),
            new AMap.LngLat(leg.to_lon, leg.to_lat),
            function (status, result) {
              if (token !== state.renderToken) {
                resolve();
                return;
              }
              if (status === "complete") {
                var path = flattenTransitPath(result);
                if (path.length > 1) {
                  setCachedRoute(leg, mode, options, path);
                  addRoutePolyline(path, color, mode, token);
                  recordRouteSuccess();
                } else {
                  requestWalkingFallbackPath(leg, color, token, "empty transit path").then(resolve);
                  return;
                }
              } else {
                requestWalkingFallbackPath(leg, color, token, describeRouteFailure(status, result)).then(resolve);
                return;
              }
              resolve();
            }
          );
        });
      } else {
        scheduleRouteRequest(function () {
            if (token !== state.renderToken) {
              resolve();
              return;
            }
        service = new AMap.Driving({
          hideMarkers: true,
          autoFitView: false,
          policy: AMap.DrivingPolicy.LEAST_TIME
        });
        state.routeServices.push(service);
        service.search(
          new AMap.LngLat(leg.from_lon, leg.from_lat),
          new AMap.LngLat(leg.to_lon, leg.to_lat),
          function (status, result) {
            if (token !== state.renderToken) {
              resolve();
              return;
            }
            if (status === "complete") {
              var path = flattenPath(result);
              if (path.length > 1) {
                setCachedRoute(leg, mode, options, path);
                addRoutePolyline(path, color, mode, token);
                recordRouteSuccess();
              } else {
                recordRouteFallback(leg, "empty driving path");
                addFallbackPolyline(leg, color, token);
              }
            } else {
              recordRouteFallback(leg, describeRouteFailure(status, result));
              addFallbackPolyline(leg, color, token);
            }
            resolve();
          }
        );
        });
      }
    });
  }

  function flattenTransitPath(routeResult) {
    var plans = routeResult && routeResult.plans;
    if (!Array.isArray(plans) || !plans.length) {
      return [];
    }

    var segments = plans[0].segments || [];
    var path = [];
    segments.forEach(function (segment) {
      appendPointList(path, segment.path);

      var transit = segment.transit;
      if (transit) {
        appendPointList(path, transit.path);
        (transit.lines || []).forEach(function (line) {
          appendPointList(path, line.path);
          appendPointList(path, line.polyline);
        });
      }

      var walking = segment.walking;
      if (walking) {
        appendPointList(path, walking.path);
        (walking.steps || []).forEach(function (step) {
          appendPointList(path, step.path);
          appendPointList(path, step.polyline);
        });
      }
    });

    return path;
  }

  function appendPointList(target, points) {
    if (!points) {
      return;
    }

    if (typeof points === "string") {
      points.split(";").forEach(function (chunk) {
        var parts = chunk.split(",");
        if (parts.length !== 2) {
          return;
        }
        var lng = Number(parts[0]);
        var lat = Number(parts[1]);
        if (Number.isFinite(lng) && Number.isFinite(lat)) {
          target.push([lng, lat]);
        }
      });
      return;
    }

    if (!Array.isArray(points)) {
      return;
    }

    points.forEach(function (point) {
      if (Array.isArray(point) && point.length >= 2) {
        target.push([point[0], point[1]]);
        return;
      }

      if (point && Number.isFinite(point.lng) && Number.isFinite(point.lat)) {
        target.push([point.lng, point.lat]);
        return;
      }

      if (point && Number.isFinite(point.L) && Number.isFinite(point.N)) {
        target.push([point.L, point.N]);
      }
    });
  }

  function renderLegs(days, token, options) {
    var promises = [];

    days.forEach(function (day) {
      var color = day.color || "#0EA5E9";
      (day.legs || []).forEach(function (leg) {
        if (state.routeStats) {
          state.routeStats.total += 1;
        }
        promises.push(requestLegPath(leg, color, token, options));
      });
    });

    return Promise.all(promises);
  }

  function collectBoundsPoints(days) {
    var points = [];

    days.forEach(function (day) {
      (day.stops || []).forEach(function (stop) {
        if (isValidCoord(stop.lat, stop.lon)) {
          points.push(toLngLat(stop));
        }
      });
    });

    return points;
  }

  function applyMapView(payload, days) {
    var points = collectBoundsPoints(days);
    if (points.length > 1) {
      state.map.setFitView(state.overlays, false, [90, 90, 90, 90]);
      return;
    }

    var center = payload && payload.center;
    if (center && isValidCoord(center.lat, center.lon)) {
      state.map.setZoomAndCenter(DEFAULT_ZOOM, [center.lon, center.lat]);
      return;
    }

    state.map.setZoomAndCenter(DEFAULT_ZOOM, DEFAULT_CENTER);
  }

  function render(payload, options) {
    options = options || {};
    var containerId = options.containerId || DEFAULT_CONTAINER_ID;
    state.legendTarget = resolveTarget(options.legendSelector || "#map-legend");
    state.listTarget = resolveTarget(options.listSelector || "#day-list");
    state.statusTarget = resolveTarget(options.statusSelector || "#map-status");
    state.togglesTarget = resolveTarget(options.togglesSelector || "#map-toggles");

    validatePayload(payload);
    initMap(containerId);
    clearMap();
    state.renderToken += 1;
    var token = state.renderToken;
    resetRouteStats();

    var focusDay = options.focusDay || "all";
    var days = collectDisplayDays(payload, focusDay);
    state.lastOptions = buildRenderOptions(options, {});

    renderLegend(days);
    renderDayCards(days);
    renderToggles(payload, {
      containerId: containerId,
      focusDay: focusDay,
      legendSelector: options.legendSelector || "#map-legend",
      listSelector: options.listSelector || "#day-list",
      statusSelector: options.statusSelector || "#map-status",
      togglesSelector: options.togglesSelector || "#map-toggles"
    });
    renderModeControls(payload, buildRenderOptions(options, {
      modeSelector: options.modeSelector || "#route-mode-controls"
    }));

    if (!days.length) {
      setStatus("当前筛选条件下没有可渲染的地图数据。", false);
      applyMapView(payload, []);
      return Promise.resolve();
    }

    renderStops(days, token);
    setStatus("正在绘制路线与点位，请稍候。", false);

    return renderLegs(days, token, options)
      .then(function () {
        if (token !== state.renderToken) {
          return;
        }
        applyMapView(payload, days);
        var routeMessage = "";
        if (state.routeStats && state.routeStats.total) {
          routeMessage =
            " 路线：成功 " +
            state.routeStats.success +
            "/" +
            state.routeStats.total +
            "，步行兜底 " +
            state.routeStats.rerouted +
            "，回退直线 " +
            state.routeStats.fallback +
            "。";
          if (state.routeStats.failures.length) {
            routeMessage += " 失败示例：" + state.routeStats.failures.join("；");
          }
        }
        setStatus(
          "渲染完成：显示 " +
            days.length +
            " 天、" +
            days.reduce(function (count, day) {
              return count + (day.stops || []).filter(function (stop) {
                return isValidCoord(stop.lat, stop.lon);
              }).length;
            }, 0) +
            " 个节点。" +
            routeMessage,
          state.routeStats && state.routeStats.fallback > 0
        );
      })
      .catch(function (error) {
        console.error(error);
        setStatus("路线服务部分失败，已回退为直线展示。", true);
        applyMapView(payload, days);
      });
  }

  window.renderTravelMap = function (mapPayload, options) {
    state.latestPayload = mapPayload;
    return render(mapPayload, options).catch(function (error) {
      console.error(error);
      setStatus(error.message || "地图渲染失败。", true);
      throw error;
    });
  };

  window.renderTravelMap.reload = function (options) {
    if (!state.latestPayload) {
      return Promise.reject(new Error("No previous mapPayload is available."));
    }
    return window.renderTravelMap(state.latestPayload, options);
  };
})();
