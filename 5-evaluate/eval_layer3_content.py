"""层次三：主 Agent 内容质量 LLM Judge 测评入口。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from eval_main_agent import _L3_TEST, run_layer3


def main() -> None:
    parser = argparse.ArgumentParser(description="层次三：内容质量 LLM Judge 测评")
    parser.add_argument("--cases", type=int, default=None, help="最大对照组数量")
    parser.add_argument("--out", type=str, default=None, help="结果输出 JSON 文件路径")
    args = parser.parse_args()

    with open(_L3_TEST, encoding="utf-8") as f:
        test_data = json.load(f)

    result = run_layer3(test_data, max_cases=args.cases)
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
