"""
RAG 在线查询模块 — 供 B 组 Agent 调用

用法:
    from search_notes import search_notes

    results = search_notes(
        query="成都亲子游推荐景点",
        city="成都",
        category="亲子",
        strategy="hybrid",   # "dense" | "hybrid" | "filter"
        top_k=5,
    )

返回:
    list[dict]，每条包含 chunk_id / score / chunk_text / metadata
"""

from __future__ import annotations

import pickle
import sys
from functools import lru_cache
from pathlib import Path

# ── 路径：指向第一部分的交付物 ────────────────────────────────────────────
_RAG_ROOT = Path(__file__).resolve().parents[1] / "1-rag_pipeline_delivery"
_BM25_PKL = _RAG_ROOT / "data" / "db" / "bm25" / "bm25_index.pkl"
_CHROMA_DIR = _RAG_ROOT / "data" / "db" / "chroma"

# 把 rag 包加入 sys.path，供 embedder / config 导入
if str(_RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(_RAG_ROOT))

# ── 城市名规范化（中英文均可）────────────────────────────────────────────
_CITY_NORM: dict[str, str] = {
    "chengdu": "成都", "成都": "成都",
    "shanghai": "上海", "上海": "上海",
    "beijing": "北京", "北京": "北京",
    "xian": "西安", "xi'an": "西安", "西安": "西安",
    "hangzhou": "杭州", "杭州": "杭州",
    "chongqing": "重庆", "重庆": "重庆",
    "xiamen": "厦门", "厦门": "厦门",
    "guangzhou": "广州", "广州": "广州",
    "shenzhen": "深圳", "深圳": "深圳",
    "hongkong": "香港", "hong kong": "香港", "香港": "香港",
}


def _normalize_city(city: str) -> str:
    return _CITY_NORM.get(city.strip(), _CITY_NORM.get(city.strip().lower(), city.strip()))


# ── BM25 加载（进程内单例）────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_bm25():
    """加载第一部分生成的 BM25 pkl，返回 (bm25_obj, chunk_ids, chunk_texts)。"""
    if not _BM25_PKL.exists():
        return None, [], []

    import jieba
    from rank_bm25 import BM25Okapi

    with open(_BM25_PKL, "rb") as f:
        data = pickle.load(f)

    chunk_ids: list[str] = data["chunk_ids"]
    chunk_texts: list[str] = data["chunk_texts"]

    # pkl 里的 tokenized_corpus 直接复用，无需重新分词
    tokenized_corpus: list[list[str]] = data["tokenized_corpus"]
    bm25 = BM25Okapi(tokenized_corpus)

    return bm25, chunk_ids, chunk_texts


# ── ChromaDB 加载（进程内单例，可选）────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_chroma():
    """尝试加载 ChromaDB collection，若不存在则返回 None。"""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        col = client.get_collection("travel_guides")
        return col
    except Exception:
        return None


# ── 停用词（与第一部分保持一致）──────────────────────────────────────────
_STOPWORDS = set(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 他 她 它 们 那 里 为 什么 怎么 吗 吧 呢 啊 哦 嗯 呀 哈 哪 几 多 大 小 "
    "可以 这个 这里 那个 那里 还 而 但 与 及 等 从 对 被 把 让 向 于 以 之 其 如 "
    "能 想 比较 真的 非常 特别 一定 可能 应该 已经 还是 或者 而且 但是 因为 所以 如果 "
    "虽然 不过 然后 这样 那样 什么样 怎样 多少 时候 一下 一些 这些 那些 出来 过来 "
    "起来 下来 上来 进去 出去 回来 过去".split()
)


def _tokenize(text: str) -> list[str]:
    try:
        import jieba
        return [w for w in jieba.cut(text) if w.strip() and w not in _STOPWORDS]
    except ImportError:
        import re
        return [w for w in re.findall(r"[一-鿿A-Za-z0-9]+", text.lower())
                if w not in _STOPWORDS]


# ── 元数据还原（ChromaDB 把 list 存成逗号字符串）────────────────────────
def _restore_metadata(raw: dict) -> dict:
    """将 ChromaDB 返回的扁平 metadata 还原为标准结构。"""
    list_fields = {"tags", "poi_names", "districts", "travel_type_tags",
                   "time_suggestions", "poi_types"}
    restored: dict = {}
    for k, v in raw.items():
        if k in list_fields:
            if isinstance(v, str):
                restored[k] = [x.strip() for x in v.split(",") if x.strip()] if v else []
            else:
                restored[k] = v if isinstance(v, list) else []
        else:
            restored[k] = v
    # 补齐缺失字段，保证 B 组拿到的结构一致
    for field in list_fields:
        restored.setdefault(field, [])
    restored.setdefault("source_id", "")
    restored.setdefault("city", "")
    restored.setdefault("content_type", "")
    restored.setdefault("title", "")
    restored.setdefault("source_platform", "xiaohongshu")
    restored.setdefault("chunk_index", 0)
    return restored


# ── BM25 文本中提取 metadata（BM25 pkl 不含 metadata，从 chunk_text 提取城市）
def _bm25_city_filter(chunk_ids: list[str], chunk_texts: list[str],
                      city: str) -> tuple[list[str], list[str]]:
    """
    BM25 pkl 中没有 metadata，通过 chunk_text 首行包含城市名来粗过滤。
    成都数据全是成都，若未来多城市可依赖此逻辑。
    """
    if not city:
        return chunk_ids, chunk_texts
    filtered_ids, filtered_texts = [], []
    for cid, ct in zip(chunk_ids, chunk_texts):
        if city in ct[:50]:  # 标题行通常包含城市名
            filtered_ids.append(cid)
            filtered_texts.append(ct)
    # 如果过滤后太少（城市名不在标题里），回退用全量
    if len(filtered_ids) < 10:
        return chunk_ids, chunk_texts
    return filtered_ids, filtered_texts


# ── RRF 融合 ────────────────────────────────────────────────────────────
def _rrf_fuse(
    dense_hits: list[tuple[str, float]],   # [(chunk_id, score), ...]
    bm25_hits: list[tuple[str, float]],
    k: int = 60,
    dense_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion，返回按融合分降序的 [(chunk_id, fused_score)]。"""
    scores: dict[str, float] = {}
    for rank, (cid, _) in enumerate(dense_hits):
        scores[cid] = scores.get(cid, 0.0) + dense_weight / (k + rank + 1)
    for rank, (cid, _) in enumerate(bm25_hits):
        scores[cid] = scores.get(cid, 0.0) + bm25_weight / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ── 三路检索策略 ────────────────────────────────────────────────────────
def _search_dense(query: str, city: str, top_k: int) -> list[dict]:
    """纯向量检索（需要 ChromaDB 已建好）。"""
    col = _load_chroma()
    if col is None:
        return []

    from rag.embedding.embedder import get_embeddings
    query_emb = get_embeddings([query], query_mode=True)

    where = {"city": city} if city else None
    result = col.query(
        query_embeddings=query_emb,
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for cid, doc, meta, dist in zip(
        result["ids"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        score = round(1.0 - dist, 6)  # cosine distance → similarity
        hits.append({
            "chunk_id": cid,
            "score": score,
            "chunk_text": doc,
            "metadata": _restore_metadata(meta),
        })
    return hits


def _search_bm25(query: str, city: str, top_k: int) -> list[dict]:
    """BM25 关键词检索。"""
    bm25, chunk_ids, chunk_texts = _load_bm25()
    if bm25 is None:
        return []

    filt_ids, filt_texts = _bm25_city_filter(chunk_ids, chunk_texts, city)

    from rank_bm25 import BM25Okapi
    tokenized_corpus = [_tokenize(t) for t in filt_texts]
    local_bm25 = BM25Okapi(tokenized_corpus)

    query_tokens = _tokenize(query)
    scores = local_bm25.get_scores(query_tokens)
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

    hits = []
    for idx in top_indices:
        s = float(scores[idx])
        if s <= 0:
            continue
        hits.append({
            "chunk_id": filt_ids[idx],
            "score": round(s, 6),
            "chunk_text": filt_texts[idx],
            "metadata": {
                "source_id": filt_ids[idx].rsplit("_", 1)[0],
                "city": city,
                "content_type": "",
                "tags": [],
                "poi_names": [],
                "districts": [],
                "title": "",
                "source_platform": "xiaohongshu",
                "travel_type_tags": [],
                "time_suggestions": [],
                "poi_types": [],
                "chunk_index": int(filt_ids[idx].rsplit("_", 1)[-1])
                    if "_" in filt_ids[idx] else 0,
            },
        })
    return hits


def _search_hybrid(query: str, city: str, top_k: int) -> list[dict]:
    """
    Hybrid = dense + BM25 → RRF 融合。
    若 ChromaDB 不可用，自动退化为纯 BM25。
    """
    fetch = max(top_k * 3, 20)  # 多取一些再融合

    dense_hits = _search_dense(query, city, fetch)
    bm25_hits = _search_bm25(query, city, fetch)

    # 如果 dense 完全没有（ChromaDB 未建），退化 BM25
    if not dense_hits:
        return bm25_hits[:top_k]

    dense_ranked = [(h["chunk_id"], h["score"]) for h in dense_hits]
    bm25_ranked = [(h["chunk_id"], h["score"]) for h in bm25_hits]

    fused = _rrf_fuse(dense_ranked, bm25_ranked)[:top_k]

    # 用 chunk_id 回查完整信息（优先用 dense 结果，fallback BM25）
    dense_map = {h["chunk_id"]: h for h in dense_hits}
    bm25_map = {h["chunk_id"]: h for h in bm25_hits}

    results = []
    for cid, fused_score in fused:
        base = dense_map.get(cid) or bm25_map.get(cid)
        if base is None:
            continue
        results.append({
            "chunk_id": cid,
            "score": round(fused_score, 6),
            "chunk_text": base["chunk_text"],
            "metadata": base["metadata"],
        })
    return results


def _search_filter(query: str, city: str, category: str, top_k: int) -> list[dict]:
    """
    先用 metadata 过滤缩小范围，再做向量检索。
    ChromaDB 不可用时退化为 BM25 + 文本关键词过滤。
    """
    col = _load_chroma()
    if col is None:
        # 退化：BM25 + 在 chunk_text 里判断 category 关键词
        hits = _search_bm25(query, city, top_k * 3)
        if category:
            hits = [h for h in hits if category in h["chunk_text"]]
        return hits[:top_k]

    from rag.embedding.embedder import get_embeddings
    query_emb = get_embeddings([query], query_mode=True)

    where: dict = {}
    if city:
        where["city"] = city
    # category 映射到 content_type 或 tags 过滤
    # ChromaDB where 只支持单字段精确匹配，用 city 过滤已足够缩小范围
    result = col.query(
        query_embeddings=query_emb,
        n_results=top_k * 3,
        where=where if where else None,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for cid, doc, meta, dist in zip(
        result["ids"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        restored = _restore_metadata(meta)
        # category 二次过滤：tags 或 content_type 包含 category 关键词
        if category:
            tags_str = " ".join(restored.get("tags", []))
            ct = restored.get("content_type", "")
            if category not in tags_str and category not in ct and category not in doc:
                continue
        score = round(1.0 - dist, 6)
        hits.append({
            "chunk_id": cid,
            "score": score,
            "chunk_text": doc,
            "metadata": restored,
        })

    return sorted(hits, key=lambda x: x["score"], reverse=True)[:top_k]


# ── 公开接口 ─────────────────────────────────────────────────────────────
def search_notes(
    query: str,
    city: str = "",
    category: str = "",
    strategy: str = "hybrid",
    top_k: int = 5,
) -> list[dict]:
    """
    RAG 在线查询入口，供 B 组 Agent 直接调用。

    Args:
        query:    用户查询文本，如 "成都亲子游推荐景点"
        city:     城市（中英文均可），如 "成都" / "chengdu"
        category: 可选类别关键词，如 "亲子" / "美食"，用于 filter 策略
        strategy: 检索策略
                  "dense"  — 纯向量检索（需要 ChromaDB）
                  "hybrid" — 向量 + BM25 RRF 融合（推荐，ChromaDB 缺席时自动退化 BM25）
                  "filter" — 先 metadata 过滤再向量检索
        top_k:    返回条数

    Returns:
        list[dict]，每条格式：
        {
            "chunk_id":   str,
            "score":      float,
            "chunk_text": str,
            "metadata": {
                "source_id":        str,
                "city":             str,
                "content_type":     str,
                "tags":             list[str],
                "poi_names":        list[str],
                "districts":        list[str],
                "title":            str,
                "source_platform":  str,
                "travel_type_tags": list[str],
                "time_suggestions": list[str],
                "poi_types":        list[str],
                "chunk_index":      int,
            }
        }
    """
    norm_city = _normalize_city(city) if city else ""

    if strategy == "dense":
        return _search_dense(query, norm_city, top_k)
    elif strategy == "filter":
        return _search_filter(query, norm_city, category, top_k)
    else:  # "hybrid" 及其他未知值统一走 hybrid
        return _search_hybrid(query, norm_city, top_k)
