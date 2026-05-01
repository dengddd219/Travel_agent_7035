"""层次一：主 Agent 意图理解测评入口。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from eval_main_agent import _L1_TEST, run_layer1


def main() -> None:
    parser = argparse.ArgumentParser(description="层次一：意图理解测评")
    parser.add_argument("--cases", type=int, default=None, help="最大测试 case 数（按顶层 case 计）")
    parser.add_argument("--use-llm", action="store_true", help="使用 LLM 理解路径（默认启发式路径）")
    parser.add_argument("--out", type=str, default=None, help="结果输出 JSON 文件路径")
    args = parser.parse_args()

    with open(_L1_TEST, encoding="utf-8") as f:
        test_data = json.load(f)

    result = run_layer1(test_data, use_llm=args.use_llm, max_cases=args.cases)
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
