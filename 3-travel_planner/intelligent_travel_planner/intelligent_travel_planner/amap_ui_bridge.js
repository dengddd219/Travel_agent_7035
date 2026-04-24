// ## author:SUN Bin
// Bridge layer between our backend response and the delivered Amap renderer.
// We keep this separate so we do not need to modify the other group's map code
// just to adapt field names or city handling.
(function () {
  "use strict";

  // Canonical English city names are used in our backend; the frontend map and
  // transit preview usually work better with explicit Chinese city labels.
  var CITY_NAME_MAP = {
    "Hong Kong": "香港",
    Tokyo: "东京",
    Chengdu: "成都",
    Shanghai: "上海",
    Beijing: "北京",
    Guangzhou: "广州",
    Shenzhen: "深圳",
    Hangzhou: "杭州",
    Xian: "西安",
    Chongqing: "重庆",
    Xiamen: "厦门",
    Nanjing: "南京"
  };

  function resolveRenderCity(apiResponse, options) {
    // Prefer an explicit override, then map payload metadata, then user profile.
    if (options && options.city) {
      return options.city;
    }

    if (apiResponse && apiResponse.map_payload) {
      if (apiResponse.map_payload.city_zh) {
        return apiResponse.map_payload.city_zh;
      }
      if (apiResponse.map_payload.city) {
        return CITY_NAME_MAP[apiResponse.map_payload.city] || apiResponse.map_payload.city;
      }
    }

    if (apiResponse && apiResponse.user_profile && apiResponse.user_profile.city) {
      return CITY_NAME_MAP[apiResponse.user_profile.city] || apiResponse.user_profile.city;
    }

    return "上海";
  }

  function buildRenderOptions(apiResponse, options) {
    // Transit-related options are passed explicitly because some Amap plugins
    // do not infer the correct city reliably from POI coordinates alone.
    var city = resolveRenderCity(apiResponse, options);
    var safeOptions = options || {};
    return Object.assign({}, safeOptions, {
      city: city,
      transitCity: safeOptions.transitCity || city,
      transitCityDestination: safeOptions.transitCityDestination || city
    });
  }

  window.renderTravelMapFromPlannerResponse = function (apiResponse, options) {
    // Main integration entrypoint used by our demo/UI layer.
    if (!window.renderTravelMap) {
      throw new Error("renderTravelMap is not available. Please load amap_ui_delivery/map.js first.");
    }

    if (!apiResponse || !apiResponse.map_payload) {
      throw new Error("Planner API response does not contain map_payload.");
    }

    return window.renderTravelMap(apiResponse.map_payload, buildRenderOptions(apiResponse, options));
  };

  window.fetchAndRenderTravelPlan = async function (url, requestBody, options) {
    // Convenience helper for lightweight pages that want one-call planning +
    // immediate map rendering.
    var response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody || {})
    });

    if (!response.ok) {
      throw new Error("Planner request failed with status " + response.status);
    }

    var data = await response.json();
    window.renderTravelMapFromPlannerResponse(data, options);
    return data;
  };
})();
