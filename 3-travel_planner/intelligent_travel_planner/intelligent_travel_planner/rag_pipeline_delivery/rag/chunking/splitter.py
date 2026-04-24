"""
文档分块器

将清洗后的文本切分为适合向量检索的 chunk。
支持多种切分策略，通过 config.py 控制参数。
"""

import re
from rag.config import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    MIN_CHUNK_LENGTH,
    SHORT_DOC_THRESHOLD,
)


def chunk_document(clean_text: str, metadata: dict) -> list[dict]:
    """
    将一篇清洗后的文档切分为 chunk 列表。

    Args:
        clean_text: 清洗后的纯文本
        metadata: 原文档的 frontmatter metadata

    Returns:
        list of {
            "chunk_id": "source_id_000",
            "chunk_text": "...",
            "chunk_index": 0,
            "metadata": { 继承自原文档 }
        }
    """
    source_id = metadata.get("source_id", "unknown")
    title = metadata.get("title", "")

    # 短文档不切分
    if len(clean_text) <= SHORT_DOC_THRESHOLD:
        prefixed = f"【{title}】\n{clean_text}" if title else clean_text
        return [_make_chunk(prefixed, source_id, 0, metadata)]

    # 先尝试按景点标记（📍）切分 — 小红书帖子的天然结构
    sections = _split_by_poi_marker(clean_text)

    if sections and len(sections) > 1:
        # 按景点段落切分成功，对过长的段落再做二次切分
        chunks_text = []
        for section in sections:
            if len(section) > CHUNK_SIZE * 1.5:
                chunks_text.extend(_recursive_split(section))
            else:
                chunks_text.append(section)
    else:
        # 没有 📍 结构，使用递归切分
        chunks_text = _recursive_split(clean_text)

    # 过滤太短的 chunk
    chunks_text = [c for c in chunks_text if len(c.strip()) >= MIN_CHUNK_LENGTH]

    # 去重：相同文本的 chunk 只保留第一个
    seen_texts = set()
    unique_chunks = []
    for text in chunks_text:
        normalized = text.strip()
        if normalized not in seen_texts:
            seen_texts.add(normalized)
            unique_chunks.append(normalized)

    # 添加标题前缀 + 组装结果
    results = []
    for i, text in enumerate(unique_chunks):
        prefixed = f"【{title}】\n{text}" if title else text
        results.append(_make_chunk(prefixed, source_id, i, metadata))

    return results


def _split_by_poi_marker(text: str) -> list[str]:
    """
    按 📍 景点标记切分。

    很多小红书帖子的结构是:
        📍 景点A
        描述...
        📍 景点B
        描述...
    """
    # 匹配 📍 或者 "📍 " 开头的行
    parts = re.split(r"(?=📍)", text)
    # 过滤空段
    return [p.strip() for p in parts if p.strip()]


def _recursive_split(text: str) -> list[str]:
    """
    递归字符切分（类似 LangChain 的 RecursiveCharacterTextSplitter）。

    分隔符优先级: 双换行 > 单换行 > 句号 > 空格
    """
    separators = ["\n\n", "\n", "。", "！", "？", "，", " "]
    return _split_with_separators(text, separators, CHUNK_SIZE, CHUNK_OVERLAP)


def _split_with_separators(
    text: str,
    separators: list[str],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """用给定分隔符列表递归切分文本。"""
    if len(text) <= chunk_size:
        return [text]

    # 找到当前能用的最高优先级分隔符
    sep = None
    for s in separators:
        if s in text:
            sep = s
            break

    if sep is None:
        # 没有分隔符可用，硬切
        return _hard_split(text, chunk_size, overlap)

    # 用这个分隔符切分
    parts = text.split(sep)
    chunks = []
    current = ""

    for part in parts:
        candidate = current + sep + part if current else part

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # 如果单个 part 就超长，递归用更低优先级的分隔符
            if len(part) > chunk_size:
                remaining_seps = separators[separators.index(sep) + 1:]
                if remaining_seps:
                    chunks.extend(
                        _split_with_separators(part, remaining_seps, chunk_size, overlap)
                    )
                else:
                    chunks.extend(_hard_split(part, chunk_size, overlap))
                current = ""
            else:
                current = part

    if current:
        chunks.append(current)

    # 添加 overlap
    if overlap > 0 and len(chunks) > 1:
        chunks = _add_overlap(chunks, overlap)

    return chunks


def _hard_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """当没有合适分隔符时，按固定长度硬切。"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap if overlap > 0 else end
    return chunks


def _add_overlap(chunks: list[str], overlap: int) -> list[str]:
    """给相邻 chunk 添加重叠部分。"""
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap:] if len(chunks[i - 1]) >= overlap else chunks[i - 1]
        result.append(prev_tail + chunks[i])
    return result


def _make_chunk(text: str, source_id: str, index: int, metadata: dict) -> dict:
    """组装单个 chunk 的标准结构。"""
    chunk_id = f"{source_id}_{index:03d}"
    return {
        "chunk_id": chunk_id,
        "chunk_text": text,
        "chunk_index": index,
        "metadata": {
            "source_id": source_id,
            "city": metadata.get("city", ""),
            "content_type": metadata.get("content_type", ""),
            "tags": metadata.get("tags", []),
            "poi_names": metadata.get("poi_names", []),
            "districts": metadata.get("districts", []),
            "title": metadata.get("title", ""),
            "source_platform": metadata.get("source_platform", "xiaohongshu"),
            "travel_type_tags": metadata.get("travel_type_tags", []),
            "time_suggestions": metadata.get("time_suggestions", []),
            "poi_types": metadata.get("poi_types", []),
            "frequency": metadata.get("frequency", 0),
            "chunk_index": index,
        },
    }
