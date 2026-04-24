from pathlib import Path
from collections import Counter
import json
import re


def simple_bm25_like_score(query: str, text: str) -> float:
    tokens = [token for token in re.split(r"\s+|[，。、“”‘’：:；;（）()、/]+", query.lower()) if token]
    lowered = text.lower()
    if not tokens:
        return 0.0
    hits = sum(1 for token in tokens if token in lowered)
    return hits / len(tokens)


def evaluate_chunks(chunks_path: Path, query: str, top_k: int = 5) -> list[dict]:
    rows = json.loads(chunks_path.read_text(encoding="utf-8"))
    ranked = []
    for row in rows:
        score = simple_bm25_like_score(query, row.get("chunk_text", ""))
        if score > 0:
            ranked.append(
                {
                    "chunk_id": row.get("chunk_id"),
                    "score": score,
                    "chunk_text": row.get("chunk_text", ""),
                    "metadata": row.get("metadata", {}),
                }
            )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


def summarize_results(results: list[dict]) -> dict:
    poi_counter = Counter()
    district_counter = Counter()
    for result in results:
        metadata = result.get("metadata", {})
        poi_counter.update(metadata.get("poi_names", []))
        district_counter.update(metadata.get("districts", []))
    return {
        "recommended_pois": [name for name, _ in poi_counter.most_common(8)],
        "top_districts": [name for name, _ in district_counter.most_common(4)],
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    chunks_path = root / "data" / "db" / "chunks.json"
    if not chunks_path.exists():
        raise FileNotFoundError("Run ingest.py first to build chunks.json")
    query = "成都 美食 路线"
    results = evaluate_chunks(chunks_path, query)
    summary = summarize_results(results)
    print(json.dumps({"query": query, "results": results, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
