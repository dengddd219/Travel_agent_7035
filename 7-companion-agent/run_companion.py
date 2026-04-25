from __future__ import annotations

import json

from companion_agent import CompanionAgent
from models import CompanionState


def main() -> None:
    agent = CompanionAgent()
    state = CompanionState()

    print("Companion Agent CLI")
    print("输入 'exit' 退出。")

    while True:
        user_input = input("\nYou> ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break

        result = agent.run_turn(user_input, state=state)
        state = result.state or state

        print(f"\nAgent> {result.reply}")
        if result.cards:
            print("\nCards>")
            print(json.dumps(result.cards[:5], ensure_ascii=False, indent=2))
        if result.warnings:
            print("\nWarnings>")
            print(json.dumps(result.warnings, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
