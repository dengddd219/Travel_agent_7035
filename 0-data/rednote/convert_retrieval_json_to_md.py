#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
把 retrieval_chunks.json 转成带 frontmatter 的 Markdown 文件。
输出格式尽量对齐示例：
---
source_id: xiaohongshu_xxx
source_platform: xiaohongshu
title: "..."
city: 成都
category: 行程
content_type: transport_tip
tags: [廊桥, 江景, 灯光夜景]
poi_names: [安顺廊桥]
travel_type_tags: [leisure, photography]
time_suggestions: [evening]
poi_types: [地标]
suggested_duration_hours: 0.5
recommended_visit_period: 夜晚
mention_count: 5
frequency: 0.2778
guide_url: "..."
---

# 标题
正文...
"""

import re
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple


COMMON_CITY_SLUG = {
    "成都": "chengdu",
    "重庆": "chongqing",
    "北京": "beijing",
    "上海": "shanghai",
    "广州": "guangzhou",
    "深圳": "shenzhen",
    "杭州": "hangzhou",
    "西安": "xian",
    "南京": "nanjing",
    "武汉": "wuhan",
    "长沙": "changsha",
    "苏州": "suzhou",
    "厦门": "xiamen",
    "青岛": "qingdao",
    "昆明": "kunming",
    "大理": "dali",
    "三亚": "sanya",
    "天津": "tianjin",
    "香港": "hongkong",
    "澳门": "macau",
}


def safe_filename(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "untitled"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:120]


def slugify_city(city: str) -> str:
    city = (city or "").strip()
    if not city:
        return "unknown_city"
    if city in COMMON_CITY_SLUG:
        return COMMON_CITY_SLUG[city]
    lowered = city.lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", lowered).strip("_")
    return lowered or "unknown_city"


def normalize_whitespace(text: str) -> str:
    text = "" if text is None else str(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def yaml_scalar(value: Any, force_quote: bool = False) -> str:
    if value is None:
        return '""' if force_quote else "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not force_quote:
        return str(value)
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    if force_quote:
        return f'"{s}"'
    if s == "":
        return '""'
    if re.search(r'[:#\[\]\{\},&*!?|<>=@`"\n]', s) or s.strip() != s:
        return f'"{s}"'
    return s


def yaml_inline_list(values: Any) -> str:
    if not values:
        return "[]"
    if not isinstance(values, list):
        values = [values]

    items = []
    for item in values:
        if item is None:
            continue
        s = str(item).strip()
        if not s:
            continue
        # 按示例尽量输出不带引号的 inline list；必要时加引号
        if re.search(r'[,:\[\]\{\}"\n]', s):
            s = '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        items.append(s)
    return "[" + ", ".join(items) + "]" if items else "[]"


def load_json(path: Path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "chunks" in data and isinstance(data["chunks"], list):
            data = data["chunks"]
        elif "items" in data and isinstance(data["items"], list):
            data = data["items"]
        else:
            raise ValueError("JSON 顶层是 dict，但没有找到 chunks/items 列表。")

    if not isinstance(data, list):
        raise ValueError("JSON 顶层必须是 list，或包含 chunks/items 的 dict。")

    return data


def parse_chunk_order(chunk: Dict[str, Any]) -> Tuple[int, str]:
    metadata = chunk.get("metadata", {}) or {}
    chunk_index = metadata.get("chunk_index")
    if isinstance(chunk_index, int):
        return (chunk_index, str(chunk.get("chunk_id", "")))

    chunk_id = str(chunk.get("chunk_id", ""))
    m = re.search(r"_(\d+)$", chunk_id)
    if m:
        return (int(m.group(1)), chunk_id)
    return (10**9, chunk_id)


def group_by_source(chunks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in chunks:
        source_id = (
            str(chunk.get("source_id", "")).strip()
            or str((chunk.get("metadata", {}) or {}).get("source_id", "")).strip()
        )
        if not source_id:
            source_id = "unknown_source"
        groups.setdefault(source_id, []).append(chunk)

    for source_id in groups:
        groups[source_id].sort(key=parse_chunk_order)
    return groups


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
        elif isinstance(value, list):
            if value:
                return value
        else:
            return value
    return None


def build_frontmatter(source_id: str, chunks: List[Dict[str, Any]]) -> str:
    first = chunks[0]
    metadata = first.get("metadata", {}) or {}

    title = first_non_empty(metadata.get("title"), "")
    city = first_non_empty(metadata.get("city"), "")
    source_platform = first_non_empty(metadata.get("source_platform"), "xiaohongshu")
    category = first_non_empty(metadata.get("category"), "")
    content_type = first_non_empty(metadata.get("content_type"), "")
    tags = first_non_empty(metadata.get("tags"), [])
    poi_names = first_non_empty(metadata.get("poi_names"), [])
    travel_type_tags = first_non_empty(metadata.get("travel_type_tags"), [])
    time_suggestions = first_non_empty(metadata.get("time_suggestions"), [])
    poi_types = first_non_empty(metadata.get("poi_types"), [])
    suggested_duration_hours = first_non_empty(metadata.get("suggested_duration_hours"), metadata.get("duration_hours"), None)
    recommended_visit_period = first_non_empty(metadata.get("recommended_visit_period"), "")
    mention_count = first_non_empty(metadata.get("mention_count"), metadata.get("count"), None)
    frequency = first_non_empty(first.get("frequency"), first.get("score"), 0)
    guide_url = first_non_empty(metadata.get("guide_url"), metadata.get("url"), metadata.get("source_url"), "")

    lines = [
        "---",
        f"source_id: {yaml_scalar(source_id)}",
        f"source_platform: {yaml_scalar(source_platform)}",
        f"title: {yaml_scalar(title, force_quote=True)}",
        f"city: {yaml_scalar(city)}",
        f"category: {yaml_scalar(category)}",
        f"content_type: {yaml_scalar(content_type)}",
        f"tags: {yaml_inline_list(tags)}",
        f"poi_names: {yaml_inline_list(poi_names)}",
        f"travel_type_tags: {yaml_inline_list(travel_type_tags)}",
        f"time_suggestions: {yaml_inline_list(time_suggestions)}",
        f"poi_types: {yaml_inline_list(poi_types)}",
        f"suggested_duration_hours: {yaml_scalar(suggested_duration_hours)}",
        f"recommended_visit_period: {yaml_scalar(recommended_visit_period)}",
        f"mention_count: {yaml_scalar(mention_count)}",
        f"frequency: {yaml_scalar(frequency)}",
        f"guide_url: {yaml_scalar(guide_url, force_quote=True)}",
        "---",
    ]
    return "\n".join(lines)


def build_markdown_body(source_id: str, chunks: List[Dict[str, Any]]) -> str:
    first = chunks[0]
    metadata = first.get("metadata", {}) or {}
    title = str(first_non_empty(metadata.get("title"), source_id)).strip() or source_id

    parts = [f"# {title}", ""]
    seen = set()

    body_blocks = []
    for chunk in chunks:
        context = normalize_whitespace(chunk.get("context", "") or chunk.get("chunk_text", ""))
        if not context:
            continue
        if context in seen:
            continue
        seen.add(context)
        body_blocks.append(context)

    parts.append("\n\n".join(body_blocks).strip())
    parts.append("")
    return "\n".join(parts)


def infer_city(chunks: List[Dict[str, Any]]) -> str:
    for chunk in chunks:
        metadata = chunk.get("metadata", {}) or {}
        city = str(metadata.get("city", "")).strip()
        if city:
            return city
    return "unknown_city"


def find_latest_retrieval_json(output_dir: Path = Path("output")) -> Path:
    if not output_dir.exists():
        raise FileNotFoundError(f"找不到目录：{output_dir}")
    candidates = list(output_dir.glob("*_retrieval_chunks.json"))
    if not candidates:
        raise FileNotFoundError(f"在 {output_dir} 下没有找到 *_retrieval_chunks.json 文件")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def convert_json_to_markdown(
    json_path: Path,
    output_root: Path = Path("data/documents"),
    city_slug: str = "",
) -> Path:
    chunks = load_json(json_path)
    if not chunks:
        raise ValueError("JSON 为空，没有可转换的数据。")

    city = infer_city(chunks)
    target_slug = city_slug.strip() if city_slug else slugify_city(city)
    output_dir = output_root / target_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    groups = group_by_source(chunks)
    written = 0

    for source_id, source_chunks in groups.items():
        frontmatter = build_frontmatter(source_id, source_chunks)
        body = build_markdown_body(source_id, source_chunks)
        md_text = frontmatter + "\n\n" + body

        out_path = output_dir / f"{safe_filename(source_id)}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        written += 1

    print(f"读取文件：{json_path}")
    print(f"转换完成，共生成 {written} 个 Markdown 文件。")
    print(f"输出目录：{output_dir}")
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="把 retrieval_chunks.json 转成按帖子分组的 Markdown 文件。")
    parser.add_argument(
        "json_path",
        nargs="?",
        default="",
        help="输入的 retrieval_chunks.json 路径；不传则自动读取 output/ 下最新的 *_retrieval_chunks.json",
    )
    parser.add_argument(
        "--output-root",
        default="data/documents",
        help="输出根目录，默认 data/documents",
    )
    parser.add_argument(
        "--city-slug",
        default="",
        help="可选，手动指定城市目录名，例如 shanghai",
    )
    args = parser.parse_args()

    output_root = Path(args.output_root)
    json_path = Path(args.json_path) if args.json_path.strip() else find_latest_retrieval_json(Path("output"))

    convert_json_to_markdown(
        json_path=json_path,
        output_root=output_root,
        city_slug=args.city_slug,
    )


if __name__ == "__main__":
    main()
