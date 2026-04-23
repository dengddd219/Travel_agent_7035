"""
Markdown 文件解析器

负责从带 YAML frontmatter 的 .md 文件中提取 metadata 和正文。
"""

from pathlib import Path
from typing import Optional
import frontmatter


def parse_md_file(filepath: Path) -> Optional[dict]:
    """
    解析单个 .md 文件，返回结构化 dict。

    Returns:
        {
            "metadata": { frontmatter 中的所有字段 },
            "raw_body": "正文原始文本",
            "filepath": Path 对象
        }
        解析失败则返回 None。
    """
    try:
        post = frontmatter.load(str(filepath))
    except Exception as e:
        print(f"[WARN] 无法解析 {filepath.name}: {e}")
        return None

    metadata = dict(post.metadata)
    raw_body = post.content.strip()

    if not raw_body:
        print(f"[WARN] {filepath.name} 正文为空，跳过")
        return None

    return {
        "metadata": metadata,
        "raw_body": raw_body,
        "filepath": filepath,
    }


def load_all_documents(city_dir: Path) -> list[dict]:
    """
    加载一个城市目录下的所有 .md 文件。

    Args:
        city_dir: 城市文件夹路径，如 data/raw/chengdu/

    Returns:
        list of parse_md_file() 的返回值
    """
    docs = []
    md_files = sorted(city_dir.glob("*.md"))

    if not md_files:
        print(f"[WARN] {city_dir} 下没有找到 .md 文件")
        return docs

    for f in md_files:
        doc = parse_md_file(f)
        if doc is not None:
            docs.append(doc)

    print(f"[INFO] {city_dir.name}: 成功加载 {len(docs)}/{len(md_files)} 篇文档")
    return docs
