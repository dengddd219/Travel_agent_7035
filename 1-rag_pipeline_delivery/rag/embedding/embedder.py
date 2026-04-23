"""
Embedding 向量化模块

支持 OpenAI 和 BGE 两种 embedding 模型，通过 config.py 切换。
"""

from rag.config import (
    EMBEDDING_PROVIDER,
    OPENAI_EMBEDDING_MODEL,
    BGE_MODEL_NAME,
    EMBEDDING_BATCH_SIZE,
)


_BGE_MODEL = None


def get_embeddings(texts: list[str], query_mode: bool = False) -> list[list[float]]:
    """
    将文本列表转为向量列表。

    Args:
        texts: 待向量化的文本列表
        query_mode: 是否是查询模式（BGE 推荐查询时加前缀）

    Returns:
        list of float vectors，与 texts 一一对应
    """
    if EMBEDDING_PROVIDER == "openai":
        return _embed_openai(texts)
    elif EMBEDDING_PROVIDER == "bge":
        return _embed_bge(texts, query_mode=query_mode)
    elif EMBEDDING_PROVIDER == "chroma_default":
        return None  # ChromaDB 会用自己内置的 embedding
    else:
        raise ValueError(f"不支持的 embedding provider: {EMBEDDING_PROVIDER}")


def _embed_openai(texts: list[str]) -> list[list[float]]:
    """使用 OpenAI Embedding API。"""
    from openai import OpenAI

    client = OpenAI()  # 读取环境变量 OPENAI_API_KEY
    all_embeddings = []

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        response = client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=batch,
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
        print(f"  [Embedding] {min(i + EMBEDDING_BATCH_SIZE, len(texts))}/{len(texts)}")

    return all_embeddings


def _embed_bge(texts: list[str], query_mode: bool = False) -> list[list[float]]:
    """使用 BAAI/bge 本地模型。"""
    global _BGE_MODEL
    from sentence_transformers import SentenceTransformer

    if _BGE_MODEL is None:
        try:
            _BGE_MODEL = SentenceTransformer(BGE_MODEL_NAME, local_files_only=True)
        except Exception:
            _BGE_MODEL = SentenceTransformer(BGE_MODEL_NAME)

    # BGE 推荐查询时加前缀，入库时不加
    if query_mode:
        texts = ["为这个句子生成表示以用于检索中文文档：" + t for t in texts]

    embeddings = _BGE_MODEL.encode(
        texts,
        batch_size=EMBEDDING_BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    return embeddings.tolist()
