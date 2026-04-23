"""
BM25 关键词索引

与 ChromaDB 的向量检索互补，支持后续的混合检索（Hybrid Search）。
支持分城市索引和停用词过滤。
"""

import pickle
from typing import Optional
import jieba
from rank_bm25 import BM25Okapi
from rag.config import BM25_INDEX_DIR, BM25_INDEX_FILE

# 中文高频停用词（对 BM25 检索无帮助的功能词）
_STOPWORDS = set(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 他 她 它 们 那 里 为 什么 怎么 吗 吧 呢 啊 哦 嗯 呀 哈 哪 几 多 大 小 "
    "可以 这个 这里 那个 那里 还 而 但 与 及 等 从 对 被 把 让 向 于 以 之 其 如 "
    "能 想 比较 真的 非常 特别 一定 可能 应该 已经 还是 或者 而且 但是 因为 所以 如果 "
    "虽然 不过 然后 这样 那样 什么样 怎样 多少 时候 一下 一些 这些 那些 出来 过来 "
    "起来 下来 上来 进去 出去 回来 过去".split()
)


def _tokenize(text: str) -> list[str]:
    """jieba 分词 + 停用词过滤。"""
    return [w for w in jieba.cut(text) if w.strip() and w not in _STOPWORDS]


class BM25Store:
    def __init__(self):
        BM25_INDEX_DIR.mkdir(parents=True, exist_ok=True)
        self.chunk_ids: list[str] = []
        self.chunk_texts: list[str] = []
        self.chunk_cities: list[str] = []  # 每个 chunk 的城市
        self.tokenized_corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None
        # 分城市索引
        self._city_indices: dict[str, dict] = {}  # city -> {ids, texts, bm25}

    def build_index(self, chunk_ids: list[str], texts: list[str],
                    cities: Optional[list[str]] = None):
        """
        构建 BM25 索引（全局 + 分城市）。
        """
        self.chunk_ids = chunk_ids
        self.chunk_texts = texts
        self.chunk_cities = cities or [""] * len(chunk_ids)
        self.tokenized_corpus = [_tokenize(t) for t in texts]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

        # 分城市建索引
        self._city_indices = {}
        if cities:
            city_groups: dict[str, list[int]] = {}
            for i, c in enumerate(cities):
                city_groups.setdefault(c, []).append(i)
            for city, indices in city_groups.items():
                city_ids = [chunk_ids[i] for i in indices]
                city_texts = [texts[i] for i in indices]
                city_tokens = [self.tokenized_corpus[i] for i in indices]
                self._city_indices[city] = {
                    "ids": city_ids,
                    "texts": city_texts,
                    "bm25": BM25Okapi(city_tokens),
                }
        print(f"[INFO] BM25 索引构建完成，共 {len(chunk_ids)} 个 chunks"
              f"，{len(self._city_indices)} 个城市分索引")

    def save(self):
        """持久化索引到磁盘。"""
        data = {
            "chunk_ids": self.chunk_ids,
            "chunk_texts": self.chunk_texts,
            "chunk_cities": self.chunk_cities,
            "tokenized_corpus": self.tokenized_corpus,
        }
        with open(BM25_INDEX_FILE, "wb") as f:
            pickle.dump(data, f)
        print(f"[INFO] BM25 索引已保存到 {BM25_INDEX_FILE}")

    def load(self):
        """从磁盘加载索引。"""
        with open(BM25_INDEX_FILE, "rb") as f:
            data = pickle.load(f)
        self.chunk_ids = data["chunk_ids"]
        self.chunk_texts = data["chunk_texts"]
        self.chunk_cities = data.get("chunk_cities", [""] * len(self.chunk_ids))
        self.tokenized_corpus = data["tokenized_corpus"]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

        # 重建分城市索引
        self._city_indices = {}
        city_groups: dict[str, list[int]] = {}
        for i, c in enumerate(self.chunk_cities):
            if c:
                city_groups.setdefault(c, []).append(i)
        for city, indices in city_groups.items():
            self._city_indices[city] = {
                "ids": [self.chunk_ids[i] for i in indices],
                "texts": [self.chunk_texts[i] for i in indices],
                "bm25": BM25Okapi([self.tokenized_corpus[i] for i in indices]),
            }
        print(f"[INFO] BM25 索引已加载，共 {len(self.chunk_ids)} 个 chunks"
              f"，{len(self._city_indices)} 个城市分索引")

    def search(self, query: str, top_k: int = 10, city: str = "") -> list[dict]:
        """
        BM25 关键词检索，支持城市过滤。
        """
        tokenized_query = _tokenize(query)

        # 优先使用城市分索引
        if city and city in self._city_indices:
            ci = self._city_indices[city]
            scores = ci["bm25"].get_scores(tokenized_query)
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
            return [
                {"chunk_id": ci["ids"][i], "chunk_text": ci["texts"][i], "score": float(scores[i])}
                for i in top_indices
            ]

        # 回退全局索引
        if self.bm25 is None:
            raise RuntimeError("BM25 索引未加载，请先调用 load() 或 build_index()")
        scores = self.bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            {"chunk_id": self.chunk_ids[i], "chunk_text": self.chunk_texts[i], "score": float(scores[i])}
            for i in top_indices
        ]
