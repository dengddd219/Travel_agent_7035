# Amap UI Integration Notes

This folder contains the standalone frontend map renderer delivered for integration.

## Files

- `map.js`: main map renderer
- `map.css`: renderer styles
- `amap-env.js`: Amap key / loader config
- `integration_minimal.html`: minimal example
- `map_demo.html`: simple local demo page
- `mock_map_payload.js`: mock payload for demo / local UI verification
- `serve_demo.py`: tiny local static server helper

## Expected input

The renderer expects a `mapPayload` object with fields like:

```js
{
  center: { lat: 30.67, lon: 104.06 },
  days: [
    {
      day_index: 1,
      area: "Qingyang",
      theme: "culture",
      color: "#0f8ea8",
      stops: [
        {
          poi_name: "Kuanzhai Alley",
          lat: 30.665,
          lon: 104.049,
          district: "Qingyang",
          category: "attraction",
          time_slot: "morning"
        }
      ],
      legs: []
    }
  ]
}
```

## Minimal usage

Load:

1. `amap-env.js`
2. `map.css`
3. `map.js`

Then call:

```js
window.renderTravelMap(mapPayload, {
  containerId: "map-container",
  city: "成都"
});
```

## Notes

- Transit preview depends on AMap JS transit services.
- For integration with the planner backend, a bridge layer can transform backend response into `mapPayload`.
