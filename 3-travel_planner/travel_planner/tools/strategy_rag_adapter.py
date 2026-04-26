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
ROUTE_HINTS = ("路线", "citywalk", "CityWalk", "连成", "串联", "顺路", "一条线", "半日", "一日游", "walk")
FOOD_HINTS = (
    "美食",
    "小吃",
    "餐厅",
    "饭店",
    "火锅",
    "串串",
    "烧烤",
    "咖啡",
    "茶",
    "奶茶",
    "甜品",
    "融合菜",
    "本帮菜",
    "food",
    "restaurant",
    "cafe",
)
SHOP_HINTS = (
    "商店",
    "买手店",
    "书店",
    "集合店",
    "百货",
    "商场",
    "店",
    "market",
    "mall",
    "shop",
    "store",
)
TRANSIT_HINTS = (
    "地铁",
    "车站",
    "机场",
    "码头",
    "公交",
    "高铁",
    "火车站",
    "高铁站",
    "汽车站",
    "出站口",
    "航站楼",
    "北站",
    "南站",
    "东站",
    "西站",
    "station",
    "airport",
)
ANCHOR_TYPE_HINTS = {
    "景点",
    "街区",
    "公园",
    "博物馆",
    "寺庙",
    "古街",
    "步行街",
    "历史建筑",
    "观景台",
    "旧址",
    "地标",
    "attraction",
    "museum",
    "park",
}
FOOD_NAME_HINTS = tuple(hint for hint in FOOD_HINTS if hint != "饭店") + (
    "酸奶",
    "牛奶",
    "饮品",
    "冰激凌",
    "冰淇淋",
    "小面",
    "抄手",
    "砂锅",
    "汤锅",
    "江湖菜",
    "串串",
    "烧烤",
    "糖水",
    "豆花",
    "汤圆",
    "小笼",
    "食品",
    "甜品",
    "茶饮",
    "茶姬",
    "夜市",
    "星巴克",
    "coffee",
    "bistro",
)
FOOD_TYPE_HINTS = FOOD_HINTS + ("饮品", "奶茶店", "小吃店", "夜市", "老字号", "美食", "咖啡店")
SHOP_NAME_HINTS = (
    "商店",
    "买手店",
    "书店",
    "书局",
    "书院",
    "书房",
    "集合店",
    "百货",
    "百货公司",
    "商场",
    "旗舰店",
    "文创店",
    "中古",
    "古着",
    "潮牌",
    "market",
    "mall",
    "shop",
    "store",
    "bookstore",
)
SHOP_TYPE_HINTS = (
    "商店",
    "买手店",
    "书店",
    "书局",
    "集合店",
    "百货",
    "商场",
    "购物街",
    "商业区",
    "market",
    "mall",
    "shop",
    "store",
    "bookstore",
)
FOOD_CONTEXT_MARKERS = ("🥣", "🍲", "🥤", "🍽", "🍜", "🍢", "🍛", "☕", "🍰", "🥟", "🧋")
FOOD_CONTEXT_PHRASES = ("老字号美食", "本地美食", "美味担当", "最好吃的一顿", "好吃滴", "必点")
SHOP_CONTEXT_MARKERS = ("🛍", "🛒")
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


def _search_via_local_city_rag(
    city: str,
    queries: list[str],
    top_k: int,
) -> tuple[list[dict], list[dict]]:
    all_results: list[dict] = []
    per_query: list[dict] = []
    for query in queries:
        query_results = _rank_city_chunks(city=city, query=query, top_k=top_k)
        per_query.append(
            {
                "query": query,
                "result_count": len(query_results),
                "top_chunk_ids": [result["chunk_id"] for result in query_results[:3]],
                "search_backend": "local_city_metadata_rag",
            }
        )
        all_results.extend(query_results)

    return _dedupe_results(all_results, top_k=top_k), per_query


def _strategy_signal_count(summary: dict, results: list[dict]) -> int:
    signal_count = 0
    signal_count += len(summary.get("recommended_pois", []))
    signal_count += len(summary.get("local_pitfalls", []))
    signal_count += len(summary.get("neighborhood_notes", []))
    signal_count += max(0, len(summary.get("theme_suggestions", [])) - 1)
    for result in results:
        metadata = result.get("metadata", {})
        signal_count += len(metadata.get("poi_names", []) or [])
        signal_count += len(metadata.get("districts", []) or [])
        signal_count += len(metadata.get("tags", []) or [])
        signal_count += len(metadata.get("travel_type_tags", []) or [])
        if metadata.get("title"):
            signal_count += 1
        if metadata.get("content_type"):
            signal_count += 1
    return signal_count


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
        "recommended_pois": recommended_pois[:12],
        "theme_suggestions": theme_suggestions[:6],
        "local_pitfalls": pitfall_notes[:4],
        "neighborhood_notes": neighborhood_notes[:4],
    }


def _compact_text(text: str) -> str:
    text = re.sub(r"#[^\s#]+", "", str(text or ""))
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ，,；;。.!！?？-")


def _clip_text(text: str, limit: int = 160) -> str:
    cleaned = _compact_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip("，,；;、 ") + "…"


def _split_sentences(text: str) -> list[str]:
    sentences = []
    for part in re.split(r"[。！？!?;\n]", str(text or "")):
        candidate = _compact_text(part)
        if len(candidate) >= 8:
            sentences.append(candidate)
    return sentences


def _snippet_for_target(text: str, target: str = "", limit: int = 170) -> str:
    cleaned = _compact_text(text)
    target = str(target or "").strip()
    if target and target in cleaned:
        index = cleaned.find(target)
        start = max(0, index - 70)
        end = min(len(cleaned), index + len(target) + 110)
        window = cleaned[start:end]
        return _clip_text(window, limit)
    for sentence in _split_sentences(text):
        if not target or target in sentence:
            return _clip_text(sentence, limit)
    return _clip_text(cleaned, limit)


def _contains_any(text: str, hints: tuple[str, ...] | set[str]) -> bool:
    lowered = str(text or "").lower()
    return any(str(hint).lower() in lowered for hint in hints if str(hint).strip())


def _poi_name_variants(poi_name: str) -> list[str]:
    name = str(poi_name or "").strip()
    variants = [name]
    base = re.sub(r"[（(].*?[）)]", "", name).strip()
    if base and base != name:
        variants.append(base)
    compact = re.sub(r"\s+", "", name)
    if compact and compact not in variants:
        variants.append(compact)
    return [variant for variant in variants if len(variant) >= 2]


def _find_poi_mention(text: str, poi_name: str) -> tuple[int, str]:
    text = str(text or "")
    for variant in _poi_name_variants(poi_name):
        index = text.find(variant)
        if index >= 0:
            return index, variant
    return -1, ""


def _poi_mentioned_in_text(text: str, poi_name: str) -> bool:
    return _find_poi_mention(text, poi_name)[0] >= 0


def _poi_context_window(text: str, poi_name: str, before: int = 24, after: int = 90) -> tuple[str, str]:
    index, variant = _find_poi_mention(text, poi_name)
    if index < 0:
        return "", ""
    start = max(0, index - before)
    end = min(len(text), index + len(variant) + after)
    prefix = text[max(0, index - 8):index]
    return text[start:end], prefix


def _metadata_types_are_specific(poi_types: list[str], hints: tuple[str, ...] | set[str]) -> bool:
    cleaned = [item for item in poi_types if item]
    if not cleaned:
        return False
    if len(cleaned) == 1:
        return _contains_any(cleaned[0], hints)
    return all(_contains_any(item, hints) for item in cleaned)


@lru_cache(maxsize=512)
def _raw_source_text(city: str, source_id: str) -> str:
    folder_name = rag_city_folder(city)
    if not folder_name or not source_id:
        return ""
    path = RAW_DATA_ROOT / folder_name / f"{source_id}.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return text


def _source_text_for_metadata(metadata: dict) -> str:
    source_id = str(metadata.get("source_id", "") or "").strip()
    city = str(metadata.get("city", "") or "").strip()
    if not source_id or not city:
        return ""
    return _raw_source_text(city, source_id)


def _infer_poi_role(
    *,
    poi_name: str,
    metadata: dict,
    chunk_text: str,
    position: int,
    total: int,
) -> str:
    content_type = str(metadata.get("content_type", "") or "").lower()
    poi_types = [str(item).strip() for item in metadata.get("poi_types", []) or []]
    source_text = chunk_text if _poi_mentioned_in_text(chunk_text, poi_name) else _source_text_for_metadata(metadata)
    context, prefix = _poi_context_window(source_text or chunk_text, poi_name)
    local_text = " ".join([poi_name, content_type, context])

    if _contains_any(poi_name, TRANSIT_HINTS) or _metadata_types_are_specific(poi_types, TRANSIT_HINTS):
        return "transit"
    if (
        _contains_any(poi_name, FOOD_NAME_HINTS)
        or _contains_any(prefix, FOOD_CONTEXT_MARKERS)
        or _contains_any(context, FOOD_CONTEXT_PHRASES)
        or _metadata_types_are_specific(poi_types, FOOD_TYPE_HINTS)
    ):
        return "food"
    if (
        _contains_any(poi_name, SHOP_NAME_HINTS)
        or _contains_any(prefix, SHOP_CONTEXT_MARKERS)
        or _metadata_types_are_specific(poi_types, SHOP_TYPE_HINTS)
    ):
        # Bookstores and shops can be useful stops, but should not become anchors.
        return "optional_shop"
    if content_type in {"pitfall", "avoid_guide"} and _contains_any(local_text, PITFALL_HINTS):
        return "pitfall"
    if content_type in {"route_plan", "attraction_guide", "hidden_gem", "family_route"}:
        if position == 0:
            return "anchor"
        if total <= 4 or position <= 4:
            return "nearby_walk"
    if _metadata_types_are_specific(poi_types, ANCHOR_TYPE_HINTS):
        return "anchor" if position <= 2 else "nearby_walk"
    return "nearby_walk" if _contains_any(local_text, ROUTE_HINTS) else "optional"


def _route_sequence_from_result(result: dict) -> list[str]:
    metadata = result.get("metadata", {}) or {}
    chunk_text = str(result.get("chunk_text", "") or "")
    content_type = str(metadata.get("content_type", "") or "")
    poi_names = [
        str(item).strip()
        for item in metadata.get("poi_names", []) or []
        if str(item).strip()
    ]
    if not poi_names:
        return []
    source_text = chunk_text
    if not any(_poi_mentioned_in_text(chunk_text, poi_name) for poi_name in poi_names):
        source_text = _source_text_for_metadata(metadata) or chunk_text
    mentioned_pois = [poi_name for poi_name in poi_names if _poi_mentioned_in_text(source_text, poi_name)]
    if mentioned_pois:
        return mentioned_pois[:8] if content_type == "route_plan" or _contains_any(source_text[:360], ROUTE_HINTS) else mentioned_pois[:4]
    if content_type == "route_plan" or _contains_any(chunk_text[:360], ROUTE_HINTS):
        return poi_names[:8]
    return poi_names[:4]


def _build_strategy_evidence(results: list[dict]) -> dict:
    evidence_chunks: list[dict] = []
    poi_evidence_map: dict[str, list[dict]] = {}
    district_evidence_map: dict[str, list[dict]] = {}
    pitfall_evidence: list[dict] = []
    route_pair_scores: dict[tuple[str, str], dict] = {}
    poi_role_priority = {
        "anchor": 6,
        "nearby_walk": 5,
        "food": 4,
        "optional_shop": 3,
        "optional": 2,
        "pitfall": 1,
        "transit": 0,
    }
    poi_roles: dict[str, str] = {}

    for result in sorted(results, key=lambda item: item.get("score", 0), reverse=True)[:8]:
        metadata = result.get("metadata", {}) or {}
        chunk_text = str(result.get("chunk_text", "") or "")
        chunk_id = str(result.get("chunk_id", "") or "")
        score = float(result.get("score", 0) or 0)
        title = str(metadata.get("title", "") or "").strip()
        content_type = str(metadata.get("content_type", "") or "").strip()
        poi_names = [
            str(item).strip()
            for item in metadata.get("poi_names", []) or []
            if str(item).strip()
        ][:10]
        districts = [
            str(item).strip()
            for item in metadata.get("districts", []) or []
            if str(item).strip()
        ][:6]
        tags = [
            str(item).strip()
            for item in metadata.get("tags", []) or []
            if str(item).strip()
        ][:10]
        route_sequence = _route_sequence_from_result(result)
        roles = {
            poi_name: _infer_poi_role(
                poi_name=poi_name,
                metadata=metadata,
                chunk_text=chunk_text,
                position=index,
                total=len(poi_names),
            )
            for index, poi_name in enumerate(poi_names)
        }
        chunk_snippet = _snippet_for_target(chunk_text, route_sequence[0] if route_sequence else "", limit=190)
        pitfalls = [
            _clip_text(sentence, 140)
            for sentence in _split_sentences(chunk_text)
            if _contains_any(sentence, PITFALL_HINTS)
        ][:3]

        evidence_chunks.append(
            {
                "chunk_id": chunk_id,
                "score": score,
                "chunk_text": chunk_text,
                "snippet": chunk_snippet,
                "source_title": title,
                "content_type": content_type,
                "poi_names": poi_names,
                "poi_roles": roles,
                "route_sequence": route_sequence,
                "time_suggestions": metadata.get("time_suggestions", []) or [],
                "districts": districts,
                "tags": tags,
                "pitfalls": pitfalls,
            }
        )

        for poi_name in poi_names:
            role = roles.get(poi_name, "optional")
            key = poi_name.strip().lower()
            if not key:
                continue
            if poi_role_priority.get(role, 0) > poi_role_priority.get(poi_roles.get(key, ""), 0):
                poi_roles[key] = role
            companions = [item for item in route_sequence if item != poi_name][:4]
            poi_evidence_map.setdefault(key, []).append(
                {
                    "poi_name": poi_name,
                    "chunk_id": chunk_id,
                    "score": score,
                    "snippet": _snippet_for_target(chunk_text, poi_name, limit=180),
                    "source_title": title,
                    "content_type": content_type,
                    "role": role,
                    "companions": companions,
                }
            )

        for district in districts:
            key = district.strip()
            district_evidence_map.setdefault(key, []).append(
                {
                    "chunk_id": chunk_id,
                    "score": score,
                    "snippet": chunk_snippet,
                    "source_title": title,
                }
            )

        for pitfall in pitfalls:
            targets = poi_names[:3] or ["city"]
            for target in targets:
                pitfall_evidence.append(
                    {
                        "scope": "poi" if target != "city" else "city",
                        "target": target,
                        "chunk_id": chunk_id,
                        "snippet": pitfall,
                        "source_title": title,
                    }
                )

        for left, right in zip(route_sequence, route_sequence[1:]):
            if roles.get(left) in {"food", "optional_shop", "optional", "transit", "pitfall"} and roles.get(right) in {
                "food",
                "optional_shop",
                "optional",
                "transit",
                "pitfall",
            }:
                continue
            left_key = left.strip().lower()
            right_key = right.strip().lower()
            if not left_key or not right_key or left_key == right_key:
                continue
            pair_key = tuple(sorted((left_key, right_key)))
            strength = min(1.0, 0.65 + 0.05 * max(0, len(route_sequence) - 2) + min(score, 5.0) / 30.0)
            current = route_pair_scores.get(pair_key)
            if current and current["strength"] >= strength:
                continue
            route_pair_scores[pair_key] = {
                "from": left,
                "to": right,
                "strength": round(strength, 3),
                "chunk_id": chunk_id,
                "evidence": _snippet_for_target(chunk_text, left, limit=150),
                "source_title": title,
            }

    for entries in poi_evidence_map.values():
        entries.sort(key=lambda item: item.get("score", 0), reverse=True)
        del entries[3:]
    for entries in district_evidence_map.values():
        entries.sort(key=lambda item: item.get("score", 0), reverse=True)
        del entries[3:]

    return {
        "evidence_chunks": evidence_chunks,
        "strategy_evidence_by_poi": poi_evidence_map,
        "strategy_evidence_by_district": district_evidence_map,
        "poi_roles": poi_roles,
        "route_pair_hints": sorted(
            route_pair_scores.values(),
            key=lambda item: item["strength"],
            reverse=True,
        )[:12],
        "pitfall_evidence": pitfall_evidence[:12],
    }


def _apply_content_type_quota(
    results: list[dict],
    min_route_plan: int = 2,
    min_pitfall: int = 1,
) -> list[dict]:
    """Reorder *results* so route_plan and pitfall types appear early enough.

    Does NOT drop any items – only adjusts order so downstream consumers
    see at least *min_route_plan* route-type chunks and *min_pitfall*
    pitfall-type chunks near the top.
    """
    PITFALL_TYPES = {"pitfall", "avoid_guide"}
    ROUTE_TYPES = {"route_plan", "attraction_guide", "hidden_gem", "family_route"}

    route_items = [r for r in results if str(r.get("metadata", {}).get("content_type", "")).lower() in ROUTE_TYPES]
    pitfall_items = [r for r in results if str(r.get("metadata", {}).get("content_type", "")).lower() in PITFALL_TYPES]
    other_items = [r for r in results if r not in route_items and r not in pitfall_items]

    ordered = route_items[:min_route_plan] + pitfall_items[:min_pitfall]
    seen_ids = {id(r) for r in ordered}
    for r in route_items[min_route_plan:] + pitfall_items[min_pitfall:] + other_items:
        if id(r) not in seen_ids:
            ordered.append(r)
            seen_ids.add(id(r))

    return ordered


def get_strategy_context(
    city: str,
    queries: list[str],
    travel_type: str = "leisure",
    top_k: int = 8,
) -> dict:
    city_info = city_name_bundle(city)
    diagnostics: dict[str, str] = {}
    local_results, local_queries = _search_via_local_city_rag(
        city=city,
        queries=queries,
        top_k=top_k,
    )
    local_summary = _summarize_strategy(local_results, travel_type=travel_type)
    local_signal_count = _strategy_signal_count(local_summary, local_results)

    final_results = local_results
    per_query = local_queries
    strategy_summary = local_summary
    retrieval_mode = "local_city_metadata_rag"
    source = "strategy_rag_adapter"

    try:
        group_a_results, group_a_queries = _search_via_group_a(
            city=city,
            queries=queries,
            travel_type=travel_type,
            top_k=top_k,
        )
        group_a_summary = _summarize_strategy(group_a_results, travel_type=travel_type)
        group_a_signal_count = _strategy_signal_count(group_a_summary, group_a_results)

        if group_a_signal_count > local_signal_count:
            final_results = group_a_results
            per_query = group_a_queries
            strategy_summary = group_a_summary
            retrieval_mode = "group_a_search_notes_hybrid"
            source = "search_notes"
            diagnostics["strategy_source_decision"] = "preferred_group_a_search_notes"
        elif group_a_signal_count > 0:
            diagnostics["strategy_source_decision"] = "kept_local_city_rag_group_a_used_as_secondary"
            diagnostics["group_a_signal_count"] = str(group_a_signal_count)
            diagnostics["local_signal_count"] = str(local_signal_count)
            per_query = local_queries + group_a_queries
            retrieval_mode = "local_city_metadata_rag+group_a_search_notes_hybrid"
        else:
            diagnostics["strategy_source_decision"] = "ignored_group_a_low_signal"
            diagnostics["group_a_signal_count"] = str(group_a_signal_count)
            diagnostics["local_signal_count"] = str(local_signal_count)
            per_query = local_queries + group_a_queries
    except Exception as exc:
        diagnostics["group_a_fallback_reason"] = f"{type(exc).__name__}: {exc}"

    final_results = _apply_content_type_quota(final_results)

    evidence = _build_strategy_evidence(final_results)

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
        **evidence,
        "source": source,
    }
