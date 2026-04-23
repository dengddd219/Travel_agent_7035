from __future__ import annotations

from collections import Counter
from functools import lru_cache
import importlib
from pathlib import Path
import re
import sys

try:
    import jieba  # type: ignore
except Exception:  # pragma: no cover - fallback path
    jieba = None

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except Exception:  # pragma: no cover - fallback path
    BM25Okapi = None


RAG_DELIVERY_ROOT = (
    Path(__file__).resolve().parents[2] / "rag_pipeline_delivery"
)


CITY_FOLDER_MAP = {
    "chengdu": "chengdu",
    "成都": "chengdu",
    "Chengdu": "chengdu",
    "shanghai": "shanghai",
    "上海": "shanghai",
    "Shanghai": "shanghai",
    "beijing": "beijing",
    "北京": "beijing",
    "Beijing": "beijing",
    "xian": "xian",
    "xi'an": "xian",
    "西安": "xian",
    "Xian": "xian",
    "hangzhou": "hangzhou",
    "杭州": "hangzhou",
    "Hangzhou": "hangzhou",
    "chongqing": "chongqing",
    "重庆": "chongqing",
    "Chongqing": "chongqing",
    "xiamen": "xiamen",
    "厦门": "xiamen",
    "Xiamen": "xiamen",
    "guangzhou": "guangzhou",
    "广州": "guangzhou",
    "Guangzhou": "guangzhou",
    "shenzhen": "shenzhen",
    "深圳": "shenzhen",
    "Shenzhen": "shenzhen",
    "nanjing": "nanjing",
    "南京": "nanjing",
    "Nanjing": "nanjing",
    "hong kong": "hongkong",
    "香港": "hongkong",
    "Hong Kong": "hongkong",
}

RAW_DATA_ROOT = RAG_DELIVERY_ROOT / "data" / "raw"
PITFALL_HINTS = ("避坑", "不要", "别去", "建议", "最好", "记得", "排队", "踩雷")


def _city_folder(city: str) -> str | None:
    return CITY_FOLDER_MAP.get(city.strip(), CITY_FOLDER_MAP.get(city.strip().lower()))


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    if jieba is not None:
        return [token.strip() for token in jieba.cut(text) if token.strip()]
    return re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text.lower())


@lru_cache(maxsize=16)
def _load_city_chunks(city: str) -> tuple[dict, ...]:
    folder_name = _city_folder(city)
    if not folder_name:
        return tuple()
    city_dir = RAW_DATA_ROOT / folder_name
    if not city_dir.exists():
        return tuple()

    if str(RAG_DELIVERY_ROOT) not in sys.path:
        sys.path.insert(0, str(RAG_DELIVERY_ROOT))

    try:
        load_all_documents = importlib.import_module("rag.utils.md_parser").load_all_documents
        clean_text = importlib.import_module("rag.cleaning.cleaner").clean_text
        chunk_document = importlib.import_module("rag.chunking.splitter").chunk_document
    except Exception:
        return tuple()

    docs = load_all_documents(city_dir)
    all_chunks: list[dict] = []
    for doc in docs:
        title = doc["metadata"].get("title", "")
        cleaned = clean_text(doc["raw_body"], title=title)
        if len(cleaned.strip()) < 20:
            continue
        all_chunks.extend(chunk_document(cleaned, doc["metadata"]))
    return tuple(all_chunks)


@lru_cache(maxsize=16)
def _build_city_bm25(city: str):
    chunks = _load_city_chunks(city)
    if not chunks or BM25Okapi is None:
        return None
    corpus = [_tokenize(chunk["chunk_text"]) for chunk in chunks]
    return BM25Okapi(corpus)


def _fallback_score(query: str, chunk_text: str) -> float:
    query_tokens = set(_tokenize(query))
    chunk_tokens = set(_tokenize(chunk_text))
    if not query_tokens or not chunk_tokens:
        return 0.0
    return len(query_tokens & chunk_tokens) / max(len(query_tokens), 1)


def _rank_city_chunks(city: str, query: str, top_k: int) -> list[dict]:
    chunks = list(_load_city_chunks(city))
    if not chunks:
        return []

    bm25 = _build_city_bm25(city)
    scores: list[float]
    if bm25 is not None:
        scores = [float(score) for score in bm25.get_scores(_tokenize(query))]
    else:  # pragma: no cover - only used when rank_bm25 is unavailable
        scores = [_fallback_score(query, chunk["chunk_text"]) for chunk in chunks]

    ranked_indices = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[: max(top_k, 1)]
    results = []
    for index in ranked_indices:
        chunk = chunks[index]
        score = scores[index]
        if score <= 0:
            continue
        results.append(
            {
                "chunk_id": chunk["chunk_id"],
                "score": round(float(score), 6),
                "chunk_text": chunk["chunk_text"],
                "metadata": chunk["metadata"],
            }
        )
    return results


def _dedupe_results(results: list[dict], top_k: int) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for result in sorted(results, key=lambda item: item["score"], reverse=True):
        chunk_id = result["chunk_id"]
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        deduped.append(result)
        if len(deduped) >= top_k:
            break
    return deduped


def _summarize_strategy(results: list[dict], travel_type: str) -> dict:
    recommended_pois: list[str] = []
    poi_seen: set[str] = set()
    theme_counter: Counter[str] = Counter()
    pitfall_notes: list[str] = []
    district_counter: Counter[str] = Counter()

    for result in results:
        metadata = result.get("metadata", {})
        for poi_name in metadata.get("poi_names", []) or []:
            key = poi_name.strip().lower()
            if key and key not in poi_seen:
                poi_seen.add(key)
                recommended_pois.append(poi_name.strip())
        for tag in (metadata.get("travel_type_tags", []) or []) + (metadata.get("tags", []) or []):
            tag_text = str(tag).strip()
            if tag_text:
                theme_counter[tag_text] += 1
        for district in metadata.get("districts", []) or []:
            district_text = str(district).strip()
            if district_text:
                district_counter[district_text] += 1

        text = result.get("chunk_text", "")
        if any(hint in text for hint in PITFALL_HINTS):
            sentence = re.split(r"[。！？!?;\n]", text, maxsplit=1)[0].strip()
            if sentence:
                pitfall_notes.append(sentence[:120])

    neighborhood_notes = [
        {
            "district": district,
            "note": "Frequently mentioned in retrieved travel notes and worth clustering in the route.",
        }
        for district, _ in district_counter.most_common(3)
    ]
    theme_suggestions = [tag for tag, _ in theme_counter.most_common(6)]
    if travel_type not in theme_suggestions:
        theme_suggestions.insert(0, travel_type)

    return {
        "recommended_pois": recommended_pois[:8],
        "theme_suggestions": theme_suggestions[:6],
        "local_pitfalls": pitfall_notes[:4],
        "neighborhood_notes": neighborhood_notes,
    }


def get_strategy_context(
    city: str,
    queries: list[str],
    travel_type: str = "leisure",
    top_k: int = 5,
) -> dict:
    all_results: list[dict] = []
    per_query: list[dict] = []
    for query in queries:
        query_results = _rank_city_chunks(city=city, query=query, top_k=top_k)
        per_query.append(
            {
                "query": query,
                "result_count": len(query_results),
                "top_chunk_ids": [result["chunk_id"] for result in query_results[:3]],
            }
        )
        all_results.extend(query_results)

    final_results = _dedupe_results(all_results, top_k=top_k)
    strategy_summary = _summarize_strategy(final_results, travel_type=travel_type)
    return {
        "city": city,
        "travel_type": travel_type,
        "retrieval_mode": "local_bm25_rag_adapter",
        "query_bundle": queries,
        "queries": per_query,
        "results": final_results,
        **strategy_summary,
        "source": "strategy_rag_adapter",
    }
