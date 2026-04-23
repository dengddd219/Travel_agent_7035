window.mockMapPayload = {
  center: { lat: 31.2179, lon: 121.4664 },
  days: [
    {
      day_index: 1,
      area: "Huangpu",
      theme: "经典地标日",
      color: "#0EA5E9",
      inter_stop_distance_m: 5450,
      inter_stop_duration_min: 38,
      stops: [
        {
          sequence: 1,
          poi_name: "The Bund",
          time_slot: "morning",
          category: "attraction",
          district: "Huangpu",
          lat: 31.2384,
          lon: 121.4903,
          address: "Zhongshan East 1st Road, Huangpu",
          open_hours: "Open 24 hours",
          ticket_price: 0,
          arrival_mode: "start",
          arrival_distance_m: 0,
          arrival_duration_min: 0,
          transport_hint: "Start the day in Huangpu."
        },
        {
          sequence: 2,
          poi_name: "Yu Garden",
          time_slot: "morning",
          category: "attraction",
          district: "Huangpu",
          lat: 31.2285,
          lon: 121.4907,
          address: "279 Yuyuan Old Street, Huangpu",
          open_hours: "09:00-16:30",
          ticket_price: 40,
          arrival_mode: "walking",
          arrival_distance_m: 1850,
          arrival_duration_min: 24,
          transport_hint: "Walking about 24 min (1.9 km) south along the riverside."
        },
        {
          sequence: 3,
          poi_name: "Shanghai Museum East",
          time_slot: "afternoon",
          category: "attraction",
          district: "Huangpu",
          lat: 31.231,
          lon: 121.475,
          address: "People's Square, Huangpu",
          open_hours: "09:00-17:00",
          ticket_price: 0,
          arrival_mode: "driving",
          arrival_distance_m: 3600,
          arrival_duration_min: 14,
          transport_hint: "Take a taxi about 14 min (3.6 km) west to People's Square."
        }
      ],
      legs: [
        {
          from_poi: "The Bund",
          to_poi: "Yu Garden",
          mode: "walking",
          distance_m: 1850,
          duration_min: 24,
          from_lat: 31.2384,
          from_lon: 121.4903,
          to_lat: 31.2285,
          to_lon: 121.4907,
          transport_hint: "Walking about 24 min (1.9 km)."
        },
        {
          from_poi: "Yu Garden",
          to_poi: "Shanghai Museum East",
          mode: "driving",
          distance_m: 3600,
          duration_min: 14,
          from_lat: 31.2285,
          from_lon: 121.4907,
          to_lat: 31.231,
          to_lon: 121.475,
          transport_hint: "Take a taxi about 14 min (3.6 km)."
        }
      ]
    },
    {
      day_index: 2,
      area: "Jing'an",
      theme: "博物馆与商业日",
      color: "#F97316",
      inter_stop_distance_m: 5300,
      inter_stop_duration_min: 40,
      stops: [
        {
          sequence: 1,
          poi_name: "Shanghai Natural History Museum",
          time_slot: "morning",
          category: "attraction",
          district: "Jing'an",
          lat: 31.238,
          lon: 121.4626,
          address: "510 Beijing West Road, Jing'an",
          open_hours: "09:00-17:00",
          ticket_price: 30,
          arrival_mode: "start",
          arrival_distance_m: 0,
          arrival_duration_min: 0,
          transport_hint: "Start the day in Jing'an."
        },
        {
          sequence: 2,
          poi_name: "Jing'an Temple",
          time_slot: "afternoon",
          category: "attraction",
          district: "Jing'an",
          lat: 31.2294,
          lon: 121.4447,
          address: "1686 Nanjing West Road, Jing'an",
          open_hours: "07:30-17:00",
          ticket_price: 50,
          arrival_mode: "walking",
          arrival_distance_m: 2100,
          arrival_duration_min: 26,
          transport_hint: "Walking about 26 min (2.1 km) southwest."
        },
        {
          sequence: 3,
          poi_name: "Xintiandi",
          time_slot: "evening",
          category: "food",
          district: "Huangpu",
          lat: 31.2193,
          lon: 121.473,
          address: "Taicang Road, Huangpu",
          open_hours: "10:00-22:00",
          ticket_price: 0,
          arrival_mode: "driving",
          arrival_distance_m: 3200,
          arrival_duration_min: 14,
          transport_hint: "Take a taxi about 14 min (3.2 km) to Xintiandi for dinner."
        }
      ],
      legs: [
        {
          from_poi: "Shanghai Natural History Museum",
          to_poi: "Jing'an Temple",
          mode: "walking",
          distance_m: 2100,
          duration_min: 26,
          from_lat: 31.238,
          from_lon: 121.4626,
          to_lat: 31.2294,
          to_lon: 121.4447,
          transport_hint: "Walking about 26 min (2.1 km)."
        },
        {
          from_poi: "Jing'an Temple",
          to_poi: "Xintiandi",
          mode: "driving",
          distance_m: 3200,
          duration_min: 14,
          from_lat: 31.2294,
          from_lon: 121.4447,
          to_lat: 31.2193,
          to_lon: 121.473,
          transport_hint: "Take a taxi about 14 min (3.2 km)."
        }
      ]
    },
    {
      day_index: 3,
      area: "Xuhui",
      theme: "法租界漫步日",
      color: "#10B981",
      inter_stop_distance_m: 4220,
      inter_stop_duration_min: 22,
      stops: [
        {
          sequence: 1,
          poi_name: "Wukang Road",
          time_slot: "morning",
          category: "attraction",
          district: "Xuhui",
          lat: 31.2046,
          lon: 121.4373,
          address: "Wukang Road, Xuhui",
          open_hours: "Open 24 hours",
          ticket_price: 0,
          arrival_mode: "start",
          arrival_distance_m: 0,
          arrival_duration_min: 0,
          transport_hint: "Start the day in Xuhui."
        },
        {
          sequence: 2,
          poi_name: "West Bund Museum",
          time_slot: "afternoon",
          category: "attraction",
          district: "Xuhui",
          lat: 31.1684,
          lon: 121.4655,
          address: "2555 Longteng Ave, Xuhui",
          open_hours: "10:00-18:00",
          ticket_price: 0,
          arrival_mode: "driving",
          arrival_distance_m: 3800,
          arrival_duration_min: 16,
          transport_hint: "Take a taxi about 16 min (3.8 km) to West Bund."
        },
        {
          sequence: 3,
          poi_name: "Long Museum West Bund",
          time_slot: "afternoon",
          category: "attraction",
          district: "Xuhui",
          lat: 31.167,
          lon: 121.4638,
          address: "3398 Longteng Ave, Xuhui",
          open_hours: "10:00-18:00",
          ticket_price: 50,
          arrival_mode: "walking",
          arrival_distance_m: 420,
          arrival_duration_min: 6,
          transport_hint: "Walking about 6 min (0.4 km) along the riverfront."
        }
      ],
      legs: [
        {
          from_poi: "Wukang Road",
          to_poi: "West Bund Museum",
          mode: "driving",
          distance_m: 3800,
          duration_min: 16,
          from_lat: 31.2046,
          from_lon: 121.4373,
          to_lat: 31.1684,
          to_lon: 121.4655,
          transport_hint: "Take a taxi about 16 min (3.8 km)."
        },
        {
          from_poi: "West Bund Museum",
          to_poi: "Long Museum West Bund",
          mode: "walking",
          distance_m: 420,
          duration_min: 6,
          from_lat: 31.1684,
          from_lon: 121.4655,
          to_lat: 31.167,
          to_lon: 121.4638,
          transport_hint: "Walking about 6 min (0.4 km)."
        }
      ]
    }
  ],
  all_stops: [
    { day_index: 1, color: "#0EA5E9", sequence: 1, poi_name: "The Bund", lat: 31.2384, lon: 121.4903 },
    { day_index: 1, color: "#0EA5E9", sequence: 2, poi_name: "Yu Garden", lat: 31.2285, lon: 121.4907 },
    { day_index: 1, color: "#0EA5E9", sequence: 3, poi_name: "Shanghai Museum East", lat: 31.231, lon: 121.475 },
    { day_index: 2, color: "#F97316", sequence: 1, poi_name: "Shanghai Natural History Museum", lat: 31.238, lon: 121.4626 },
    { day_index: 2, color: "#F97316", sequence: 2, poi_name: "Jing'an Temple", lat: 31.2294, lon: 121.4447 },
    { day_index: 2, color: "#F97316", sequence: 3, poi_name: "Xintiandi", lat: 31.2193, lon: 121.473 },
    { day_index: 3, color: "#10B981", sequence: 1, poi_name: "Wukang Road", lat: 31.2046, lon: 121.4373 },
    { day_index: 3, color: "#10B981", sequence: 2, poi_name: "West Bund Museum", lat: 31.1684, lon: 121.4655 },
    { day_index: 3, color: "#10B981", sequence: 3, poi_name: "Long Museum West Bund", lat: 31.167, lon: 121.4638 }
  ]
};
