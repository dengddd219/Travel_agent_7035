"""单独测试携程酒店抓取。

用法：
    python test_hotel.py
    python test_hotel.py 上海 2026-05-01 2026-05-03
"""
import sys
import json
from pathlib import Path

# 让 Python 能找到 backend/ 下的 WeatherCost 包
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from WeatherCost.weather_cost_api import search_hotels_api

# ── 参数（可在命令行覆盖） ──────────────────────────────────────────
city       = sys.argv[1] if len(sys.argv) > 1 else "北京"
check_in   = sys.argv[2] if len(sys.argv) > 2 else "2026-05-01"
check_out  = sys.argv[3] if len(sys.argv) > 3 else "2026-05-04"   # 3 晚

print(f"\n{'='*60}")
print(f"  测试携程酒店抓取")
print(f"  城市：{city}   入住：{check_in}   退房：{check_out}")
print(f"{'='*60}\n")

results = search_hotels_api(
    city=city,
    check_in_date=check_in,
    check_out_date=check_out,
)

print(f"\n{'='*60}")
print(f"  共返回 {len(results)} 家酒店")
print(f"{'='*60}")

for i, h in enumerate(results, 1):
    print(f"\n[{i}] {h.get('name', '未知')}")
    print(f"    星级   : {h.get('star_rate', '-')} 星")
    print(f"    区域   : {h.get('district', '-')}")
    print(f"    均价   : {h.get('min_price', '-')} 元/晚")
    print(f"    来源   : {h.get('source', '-')}")

if not results:
    print("\n  未抓到任何酒店，请查看上方携程的详细输出。")
