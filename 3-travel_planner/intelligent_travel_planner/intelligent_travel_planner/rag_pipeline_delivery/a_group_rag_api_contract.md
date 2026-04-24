# A Group RAG API Contract

This document describes the expected retrieval-facing contract for the strategy RAG component.

## Goal

The RAG layer should provide strategy context for the planner, not final itinerary text.

## Recommended retrieval response

```json
{
  "query": "成都亲子景点推荐",
  "city": "成都",
  "results": [
    {
      "chunk_id": "xhs_001_002",
      "score": 0.89,
      "chunk_text": "熊猫基地建议早上去，下午安排宽窄巷子。",
      "metadata": {
        "source_id": "xhs_001",
        "city": "成都",
        "content_type": "family_route",
        "tags": ["亲子", "熊猫基地"],
        "poi_names": ["成都大熊猫繁育研究基地", "宽窄巷子"],
        "districts": ["成华区", "青羊区"],
        "travel_type_tags": ["family"],
        "time_suggestions": ["morning", "afternoon"]
      }
    }
  ],
  "strategy_summary": {
    "recommended_pois": ["成都大熊猫繁育研究基地", "宽窄巷子"],
    "theme_suggestions": ["亲子", "慢节奏"],
    "local_pitfalls": ["熊猫基地建议早点去"],
    "neighborhood_notes": [
      {
        "district": "青羊区",
        "note": "适合安排下午逛吃"
      }
    ]
  }
}
```

## Minimum useful fields

- `chunk_id`
- `score`
- `chunk_text`
- `metadata.city`
- `metadata.content_type`
- `metadata.tags`
- `metadata.poi_names`
- `metadata.districts`

## Why these fields matter

- `poi_names` are forwarded into POI / route search.
- `districts` help the planner group stops by area.
- `chunk_text` and summary signals help explain why the route was chosen.
