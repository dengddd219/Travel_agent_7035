window.mockMapPayload = {
  city: "Chengdu",
  city_zh: "成都",
  center: { lat: 30.664, lon: 104.066 },
  days: [
    {
      day_index: 1,
      area: "Qingyang",
      theme: "culture",
      color: "#0f8ea8",
      inter_stop_distance_m: 2200,
      inter_stop_duration_min: 28,
      stops: [
        {
          poi_name: "宽窄巷子",
          time_slot: "morning",
          category: "attraction",
          district: "青羊区",
          lat: 30.668,
          lon: 104.049
        },
        {
          poi_name: "人民公园",
          time_slot: "afternoon",
          category: "park",
          district: "青羊区",
          lat: 30.659,
          lon: 104.055
        }
      ],
      legs: [
        {
          from_poi: "宽窄巷子",
          to_poi: "人民公园",
          mode: "walking",
          distance_m: 2200,
          duration_min: 28,
          from_lat: 30.668,
          from_lon: 104.049,
          to_lat: 30.659,
          to_lon: 104.055
        }
      ]
    }
  ]
};
