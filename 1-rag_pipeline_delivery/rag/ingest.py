"""
RAG 离线摄取管道 — 主入口

一键执行：数据加载 → 清洗 → 分块 → 向量化 → 存储

用法:
    python -m rag.ingest                     # 处理所有城市
    python -m rag.ingest --city chengdu      # 只处理成都
    python -m rag.ingest --reset             # 清空数据库后重新入库
    python -m rag.ingest --dry-run           # 只清洗+分块，不做 embedding（调试用）
"""

import argparse
from pathlib import Path
from typing import List, Optional

from rag.config import RAW_DATA_DIR, CITY_FOLDER_MAP
from rag.utils.md_parser import load_all_documents
from rag.cleaning.cleaner import clean_text
from rag.chunking.splitter import chunk_document


def ingest_city(city_dir: Path, city_name: str, dry_run: bool = False) -> List[dict]:
    """
    处理单个城市的数据。

    Returns:
        该城市的所有 chunk 列表
    """
    print(f"\n{'='*50}")
    print(f"  处理城市: {city_name} ({city_dir.name})")
    print(f"{'='*50}")

    # Step 1: 加载原始文档
    docs = load_all_documents(city_dir)
    if not docs:
        return []

    # Step 2: 清洗 + 分块
    all_chunks = []
    for doc in docs:
        title = doc["metadata"].get("title", "")
        cleaned = clean_text(doc["raw_body"], title=title)

        if len(cleaned.strip()) < 20:
            print(f"  [SKIP] {doc['filepath'].name}: 清洗后内容过短")
            continue

        chunks = chunk_document(cleaned, doc["metadata"])
        all_chunks.extend(chunks)

    print(f"  [INFO] {city_name}: {len(docs)} 篇文档 → {len(all_chunks)} 个 chunks")

    if dry_run:
        # 打印前3个 chunk 供检查
        for i, c in enumerate(all_chunks[:3]):
            print(f"\n  --- Chunk {i} ({c['chunk_id']}) ---")
            print(f"  {c['chunk_text'][:200]}...")
        print(f"\n  (dry-run 模式，跳过 embedding 和存储)")

    return all_chunks


def run_ingest(
    cities: Optional[List[str]] = None,
    reset: bool = False,
    dry_run: bool = False,
):
    """
    运行完整的离线摄取管道。

    Args:
        cities: 要处理的城市文件夹名列表（如 ["chengdu"]），None 表示全部
        reset: 是否清空数据库重新入库
        dry_run: 只做清洗和分块，不做 embedding 和存储
    """
    # 确定要处理的城市目录
    if cities:
        city_dirs = []
        for c in cities:
            d = RAW_DATA_DIR / c
            if d.exists():
                city_dirs.append((d, CITY_FOLDER_MAP.get(c, c)))
            else:
                print(f"[WARN] 城市目录不存在: {d}")
    else:
        city_dirs = [
            (d, CITY_FOLDER_MAP.get(d.name, d.name))
            for d in sorted(RAW_DATA_DIR.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        ]

    if not city_dirs:
        print("[ERROR] 没有找到任何城市数据目录")
        print(f"  请将数据放在: {RAW_DATA_DIR}/<城市英文名>/")
        return

    # 处理所有城市
    all_chunks = []
    for city_dir, city_name in city_dirs:
        chunks = ingest_city(city_dir, city_name, dry_run=dry_run)
        all_chunks.extend(chunks)

    print(f"\n{'='*50}")
    print(f"  总计: {len(all_chunks)} 个 chunks")
    print(f"{'='*50}")

    if dry_run or not all_chunks:
        return

    # Step 3: Embedding（延迟导入，dry-run 时不需要这些依赖）
    from rag.embedding.embedder import get_embeddings
    from rag.storage.chroma_store import ChromaStore
    from rag.storage.bm25_store import BM25Store

    texts = [c["chunk_text"] for c in all_chunks]
    chunk_ids = [c["chunk_id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    print("\n[INFO] 开始向量化...")
    embeddings = get_embeddings(texts)
    if embeddings is not None:
        print(f"[INFO] 向量化完成: {len(embeddings)} 个向量")
    else:
        print("[INFO] 使用 ChromaDB 内置 embedding（自动向量化）")

    # Step 4: 存入 ChromaDB
    print("\n[INFO] 写入 ChromaDB...")
    chroma = ChromaStore()
    if reset:
        print("  重置 collection...")
        chroma.reset()

    chroma.add_chunks(chunk_ids, texts, metadatas, embeddings=embeddings)
    print(f"[INFO] ChromaDB 当前总量: {chroma.count()} 个 chunks")

    # Step 5: 构建 BM25 索引（带城市信息）
    print("\n[INFO] 构建 BM25 索引...")
    cities = [c["metadata"].get("city", "") for c in all_chunks]
    bm25 = BM25Store()
    bm25.build_index(chunk_ids, texts, cities=cities)
    bm25.save()

    print("\n✅ 离线摄取完成!")


def main():
    parser = argparse.ArgumentParser(description="RAG 离线摄取管道")
    parser.add_argument(
        "--city",
        type=str,
        nargs="*",
        help="指定城市文件夹名（如 chengdu），不指定则处理全部",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="清空数据库后重新入库",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只做清洗和分块，不做 embedding 和存储（调试用）",
    )
    args = parser.parse_args()
    run_ingest(cities=args.city, reset=args.reset, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
