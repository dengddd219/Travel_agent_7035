## author:SUN Bin
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import importlib
import importlib.util
import json
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

from ..city_names import city_name_bundle, rag_city_folder


RAG_DELIVERY_ROOT = (
    Path(__file__).resolve().parents[3] / "1-rag_pipeline_delivery"
)
GROUP_A_SEARCH_NOTES_PATH = (
    Path(__file__).resolve().parents[3] / "2-rag-retrival" / "search_notes.py"
)

RAW_DATA_ROOT = RAG_DELIVERY_ROOT / "data" / "raw"
DB_DATA_ROOT = RAG_DELIVERY_ROOT / "data" / "db"
PITFALL_HINTS = ("避坑", "不要", "别去", "建议", "最好", "记得", "排队", "踩雷")
TRAVEL_CATEGORY_HINTS = {
    "family": "亲子",
    "food": "美食",
    "theme": "小众",
    "leisure": "",
}


def _city_folder(city: str) -> str | None:
    return rag_city_folder(city)


def _db_chunks_path(city: str) -> Path | None:
    """Return the persisted chunk-cache path for one city.

    We keep one JSON file per city under `rag_pipeline_delivery/data/db`.
    The runtime should prefer these cached chunks because:
    1. they are closer to the intended "RAG database" delivery format
    2. they avoid re-cleaning and re-chunking raw markdown on every run
    """
    folder_name = _city_folder(city)
    if not folder_name:
        return None
    return DB_DATA_ROOT / f"{folder_name}_chunks.json"


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    if jieba is not None:
        return [token.strip() for token in jieba.cut(text) if token.strip()]
    return re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text.lower())


def _parse_inline_frontmatter_value(raw_value: str):
    """Parse a small subset of YAML-like frontmatter values.

    We intentionally keep this parser lightweight because we do not want to
    modify the delivery package or add heavy new parsing dependencies just to
    rebuild the local RAG cache. The source markdown files mostly use:
    - strings
    - null
    - numeric values
    - `[a, b, c]` style lists
    """
    value = raw_value.strip()
    if value in {"null", "None", ""}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        parts = [part.strip() for part in inner.split(",")]
        normalized = []
        for part in parts:
            if part.startswith('"') and part.endswith('"'):
                normalized.append(part[1:-1])
            elif part.startswith("'") and part.endswith("'"):
                normalized.append(part[1:-1])
            else:
                normalized.append(part)
        return normalized
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _load_documents_from_raw(city: str) -> list[dict]:
    """Load raw markdown guides for one city using a local frontmatter parser.

    Why not call the delivery parser directly?
    - Their `md_parser.py` depends on `python-frontmatter`
    - The runtime should still work even if that optional dependency is absent

    We still rely on the delivery package for the real cleaning and chunking
    logic; this helper only restores the `metadata + raw_body` document shape.
    """
    folder_name = _city_folder(city)
    if not folder_name:
        return []
    city_dir = RAW_DATA_ROOT / folder_name
    if not city_dir.exists():
        return []

    docs: list[dict] = []
    for filepath in sorted(city_dir.glob("*.md")):
        text = filepath.read_text(encoding="utf-8")
        if text.startswith("---"):
            try:
                _, frontmatter_block, body = text.split("---", 2)
            except ValueError:
                frontmatter_block = ""
                body = text
        else:
            frontmatter_block = ""
            body = text

        metadata: dict = {}
        for line in frontmatter_block.splitlines():
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            metadata[key.strip()] = _parse_inline_frontmatter_value(raw_value)

        raw_body = body.strip()
        if not raw_body:
            continue

        docs.append(
            {
                "metadata": metadata,
                "raw_body": raw_body,
                "filepath": filepath,
            }
        )
    return docs


def _build_city_chunks_from_raw(city: str) -> tuple[dict, ...]:
    """Rebuild per-city chunks from the delivery raw corpus.

    This function still uses the delivery package's own:
    - cleaner
    - splitter

    So the cache we persist in `data/db` is based on their pipeline behavior,
    not on a separate custom chunking scheme from our side.
    """
    if str(RAG_DELIVERY_ROOT) not in sys.path:
        sys.path.insert(0, str(RAG_DELIVERY_ROOT))

    try:
        clean_text = importlib.import_module("rag.cleaning.cleaner").clean_text
        chunk_document = importlib.import_module("rag.chunking.splitter").chunk_document
    except Exception:
        return tuple()

    docs = _load_documents_from_raw(city)
    all_chunks: list[dict] = []
    for doc in docs:
        title = doc["metadata"].get("title", "")
        cleaned = clean_text(doc["raw_body"], title=title)
        if len(cleaned.strip()) < 20:
            continue
        all_chunks.extend(chunk_document(cleaned, doc["metadata"]))
    return tuple(all_chunks)


def _ensure_city_db(city: str) -> Path | None:
    """Materialize a per-city chunk cache under `data/db` if missing.

    After this runs once, the runtime no longer needs to rebuild chunks from
    raw markdown for that city on every request.
    """
    chunks_path = _db_chunks_path(city)
    if chunks_path is None:
        return None
    if chunks_path.exists():
        return chunks_path

    chunks = _build_city_chunks_from_raw(city)
    if not chunks:
        return None

    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    chunks_path.write_text(
        json.dumps(list(chunks), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chunks_path


@lru_cache(maxsize=16)
def _load_city_chunks(city: str) -> tuple[dict, ...]:
    """Load chunks for one city.

    Priority order:
    1. Use the delivered / persisted chunk cache in `data/db`
    2. If the cache is missing, build it once from `data/raw`
    3. Persist the built result back into `data/db`

    This makes the runtime behavior much closer to "using the RAG database"
    rather than repeatedly building from raw markdown on every request.
    """
    chunks_path = _db_chunks_path(city)
    if chunks_path and chunks_path.exists():
        return tuple(json.loads(chunks_path.read_text(encoding="utf-8")))

    rebuilt_path = _ensure_city_db(city)
    if rebuilt_path and rebuilt_path.exists():
        return tuple(json.loads(rebuilt_path.read_text(encoding="utf-8")))

    return tuple()


@lru_cache(maxsize=16)
def _build_city_bm25(city: str):
    chunks = _load_city_chunks(city)
    if not chunks or BM25Okapi is None:
        return None
    corpus = [_tokenize(chunk["chunk_text"]) for chunk in chunks]
    return BM25Okapi(corpus)


@lru_cache(maxsize=1)
def _load_group_a_search_notes():
    if not GROUP_A_SEARCH_NOTES_PATH.exists():
        raise FileNotFoundError(f"search_notes.py not found: {GROUP_A_SEARCH_NOTES_PATH}")

    module_name = "travel_agent_group_a_search_notes"
    spec = importlib.util.spec_from_file_location(module_name, GROUP_A_SEARCH_NOTES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module spec from {GROUP_A_SEARCH_NOTES_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    search_notes = getattr(module, "search_notes", None)
    if search_notes is None:
        raise AttributeError("search_notes.py does not expose `search_notes`.")
    return search_notes


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


def _search_via_group_a(
    city: str,
    queries: list[str],
    travel_type: str,
    top_k: int,
) -> tuple[list[dict], list[dict]]:
    search_notes = _load_group_a_search_notes()
    city_info = city_name_bundle(city)
    provider_city = city_info["city_zh"] or city_info["canonical"]
    category = TRAVEL_CATEGORY_HINTS.get(travel_type, "")

    all_results: list[dict] = []
    per_query: list[dict] = []
    for query in queries:
        query_results = search_notes(
            query=query,
            city=provider_city,
            category=category,
            strategy="hybrid",
            top_k=top_k,
        )
        per_query.append(
            {
                "query": query,
                "result_count": len(query_results),
                "top_chunk_ids": [result.get("chunk_id", "") for result in query_results[:3] if result.get("chunk_id")],
                "search_backend": "group_a_search_notes",
            }
        )
        all_results.extend(query_results)

    return _dedupe_results(all_results, top_k=top_k), per_query


def _summarize_strategy(results: list[dict], travel_type: str, city: str = "") -> dict:
    recommended_pois: list[str] = []
    poi_seen: set[str] = set()
    theme_counter: Counter[str] = Counter()
    pitfall_notes: list[str] = []
    district_counter: Counter[str] = Counter()

    # Build a set of city name variants to cross-check chunk metadata
    city_variants: set[str] = set()
    if city:
        bundle = city_name_bundle(city)
        city_variants = {bundle["canonical"].lower(), bundle["city_zh"], bundle["city_en"].lower()}

    for result in results:
        metadata = result.get("metadata", {})
        # Skip chunks whose city metadata doesn't match the requested city
        chunk_city = str(metadata.get("city", "")).strip()
        if city_variants and chunk_city and chunk_city.lower() not in city_variants:
            continue
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
        "recommended_pois": recommended_pois[:12],
        "theme_suggestions": theme_suggestions[:6],
        "local_pitfalls": pitfall_notes[:4],
        "neighborhood_notes": neighborhood_notes[:4],
    }


def get_strategy_context(
    city: str,
    queries: list[str],
    travel_type: str = "leisure",
    top_k: int = 8,
) -> dict:
    city_info = city_name_bundle(city)
    diagnostics: dict[str, str] = {}
    try:
        final_results, per_query = _search_via_group_a(
            city=city,
            queries=queries,
            travel_type=travel_type,
            top_k=top_k,
        )
        retrieval_mode = "group_a_search_notes_hybrid"
        source = "search_notes"
    except Exception as exc:
        diagnostics["group_a_fallback_reason"] = f"{type(exc).__name__}: {exc}"
        all_results: list[dict] = []
        per_query = []
        for query in queries:
            query_results = _rank_city_chunks(city=city, query=query, top_k=top_k)
            per_query.append(
                {
                    "query": query,
                    "result_count": len(query_results),
                    "top_chunk_ids": [result["chunk_id"] for result in query_results[:3]],
                    "search_backend": "local_bm25_rag_adapter",
                }
            )
            all_results.extend(query_results)
        final_results = _dedupe_results(all_results, top_k=top_k)
        retrieval_mode = "local_bm25_rag_adapter"
        source = "strategy_rag_adapter"

    strategy_summary = _summarize_strategy(final_results, travel_type=travel_type, city=city)
    return {
        "city": city_info["canonical"],
        "provider_city": city_info["city_zh"],
        "travel_type": travel_type,
        "retrieval_mode": retrieval_mode,
        "query_bundle": queries,
        "queries": per_query,
        "results": final_results,
        "adapter_diagnostics": diagnostics,
        **strategy_summary,
        "source": source,
    }
