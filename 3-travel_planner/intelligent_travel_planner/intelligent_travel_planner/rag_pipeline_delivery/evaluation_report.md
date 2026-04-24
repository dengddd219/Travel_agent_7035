# RAG Evaluation Notes

This file is a lightweight placeholder report for the delivered RAG package.

## Intended evaluation dimensions

- retrieval relevance
- POI extraction quality
- district metadata coverage
- topic coverage across cities
- duplicate chunk suppression

## Suggested checks

1. Query a city + theme such as `成都 美食 路线`.
2. Confirm retrieved chunks contain:
   - meaningful `poi_names`
   - usable `districts`
   - relevant `content_type`
3. Confirm multiple chunks do not collapse to the same repeated attraction.

## Integration note

The planner benefits most when retrieval returns:

- enough candidate POIs
- area hints
- guide summary signals

Sparse retrieval may still work, but route quality will degrade.
