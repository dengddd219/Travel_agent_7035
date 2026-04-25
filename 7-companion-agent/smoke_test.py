from __future__ import annotations

import json

from companion_agent import CompanionAgent
from models import CompanionState


def main() -> None:
    agent = CompanionAgent()
    state = CompanionState()

    turns = [
        "我在王府井，逛了一上午，找个午饭，小孩不吃辣，不喜欢北京菜，预算高一点",
        "下午还要去天安门和颐和园，时间够吗",
        "下午突然下雨了，天安门广场不想淋雨，能换吗",
        "老人在颐和园走不动了",
    ]

    for index, user_input in enumerate(turns, start=1):
        result = agent.run_turn(user_input, state=state)
        state = result.state or state
        print(f"\n=== Turn {index} ===")
        print(f"User: {user_input}")
        print(f"Intent: {result.intent}")
        print(f"Reply: {result.reply}")
        if result.cards:
            print("Cards:")
            print(json.dumps(result.cards[:3], ensure_ascii=False, indent=2))
        if result.warnings:
            print("Warnings:")
            print(json.dumps(result.warnings, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
