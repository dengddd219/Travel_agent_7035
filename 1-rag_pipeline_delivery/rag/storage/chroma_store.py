"""
ChromaDB 向量存储

负责将 chunk 向量 + metadata 写入 ChromaDB。
"""

import chromadb
from rag.config import CHROMA_DB_DIR, CHROMA_COLLECTION_NAME


class ChromaStore:
    def __init__(self):
        CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # 余弦相似度
        )

    def add_chunks(
        self,
        chunk_ids: list[str],
        texts: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]] = None,
    ):
        """
        批量写入 chunks。

        ChromaDB metadata 只支持 str/int/float/bool，
        list 类型字段需要转成逗号分隔的字符串。
        如果 embeddings 为 None，ChromaDB 会用内置模型自动生成。
        """
        processed_metas = [self._flatten_metadata(m) for m in metadatas]

        upsert_kwargs = {
            "ids": chunk_ids,
            "documents": texts,
            "metadatas": processed_metas,
        }
        if embeddings is not None:
            upsert_kwargs["embeddings"] = embeddings

        self.collection.upsert(**upsert_kwargs)

    def count(self) -> int:
        return self.collection.count()

    def reset(self):
        """清空 collection（重新入库时使用）。"""
        self.client.delete_collection(CHROMA_COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def _flatten_metadata(meta: dict) -> dict:
        """将 list 字段转为逗号分隔字符串，ChromaDB 不支持 list 值。"""
        flat = {}
        for k, v in meta.items():
            if isinstance(v, list):
                flat[k] = ",".join(str(item) for item in v) if v else ""
            elif v is None:
                flat[k] = ""
            else:
                flat[k] = v
        return flat
