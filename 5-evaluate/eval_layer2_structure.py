"""层次二：主 Agent 行程结构确定性 assert 入口。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from eval_main_agent import run_layer2


def main() -> None:
    parser = argparse.ArgumentParser(description="层次二：行程结构确定性验证")
    parser.add_argument("--itinerary-file", type=str, default=None, help="行程 JSON 或包含 itinerary_json 的响应文件")
    parser.add_argument("--out", type=str, default=None, help="结果输出 JSON 文件路径")
    args = parser.parse_args()

    result = run_layer2(itinerary_file=args.itinerary_file)
    report = {
        "eval_timestamp": datetime.now().isoformat(),
        "layer_results": [result],
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"结果已写入: {out_path}")


if __name__ == "__main__":
    main()
