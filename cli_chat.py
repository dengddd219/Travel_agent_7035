"""终端交互式旅行规划 CLI"""
import sys
import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"

def chat(message, conversation_id=None, conversation_state=None):
    payload = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if conversation_state:
        payload["conversation_state"] = conversation_state

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            d = json.loads(body)
            detail = d.get("detail", d)
            if isinstance(detail, dict):
                print("\n[错误]", detail.get("error", ""))
                print(detail.get("traceback", ""))
            else:
                print("\n[错误]", body[:1000])
        except Exception:
            print("\n[错误]", body[:1000])
        return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("  AI 旅行规划助手  (输入 'quit' 退出，'new' 开启新对话)")
    print("=" * 60)

    conversation_id = None
    conversation_state = None

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("再见！")
            break
        if user_input.lower() == "new":
            conversation_id = None
            conversation_state = None
            print("[新对话已开启]")
            continue

        print("\n[规划中，请稍候...]\n")
        result = chat(user_input, conversation_id, conversation_state)
        if result is None:
            continue

        conversation_id = result.get("conversation_id")
        conversation_state = result.get("conversation_state")

        print(result.get("report", "（无报告）"))

        hotels = result.get("hotel_recommendations", {})
        if hotels.get("hotels"):
            print("\n── 酒店推荐 ──")
            for h in hotels["hotels"][:3]:
                name = h.get("name", "")
                price = h.get("price_per_night", "")
                stars = h.get("star_rating", "")
                print(f"  • {name}  {stars}星  ¥{price}/晚")


if __name__ == "__main__":
    main()
