import os
import re
import csv
import json
import time
import math
import hashlib
import urllib.parse
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager


load_dotenv()

PROJECT_RESOURCE = os.getenv("FOUNDRY_PROJECT_RESOURCE", "")
PROJECT_API_KEY = os.getenv("FOUNDRY_PROJECT_API_KEY", "")
MODEL_NAME = os.getenv("FOUNDRY_PROJECT_DEPLOYMENT", "gpt-5-mini")
ENABLE_LLM_METADATA = os.getenv("ENABLE_LLM_METADATA", "1") == "1"

client = None
if PROJECT_RESOURCE and PROJECT_API_KEY:
    client = OpenAI(
        base_url=f"https://{PROJECT_RESOURCE}.openai.azure.com/openai/v1/",
        api_key=PROJECT_API_KEY,
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CHROME_USER_DATA_DIR = os.path.join(BASE_DIR, "chrome_profile")

MAX_NOTES = 100
SCROLL_ROUNDS = 12
POST_TEXT_LIMIT = 15000
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
MIN_CONTEXT_LEN = 80
OPEN_NOTE_WAIT = 10
POST_READ_WAIT = 3.0
ACTION_SLEEP = 2.5

CONTENT_TYPE_ENUMS = {
    "attraction_guide",
    "food_guide",
    "route_plan",
    "family_guide",
    "hidden_gem",
    "shopping_guide",
    "local_tip",
    "pitfall_warning",
    "transport_tip",
    "budget_tip",
}



def ensure_directories() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def save_json(data: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def flatten_dict(d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    items: List[tuple] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        elif isinstance(v, list):
            items.append((new_key, json.dumps(v, ensure_ascii=False)))
        else:
            items.append((new_key, v))
    return dict(items)


def save_csv(rows: List[Dict[str, Any]], path: str) -> None:
    if not rows:
        print("没有数据可保存。")
        return

    flat_rows = [flatten_dict(row) for row in rows]
    fieldnames = list(flat_rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_rows)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_list(items: Any, fallback: Optional[List[str]] = None, max_items: int = 8) -> List[str]:
    fallback = fallback or []
    if not isinstance(items, list):
        items = fallback

    cleaned: List[str] = []
    seen = set()
    for item in items:
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
        if len(cleaned) >= max_items:
            break
    return cleaned or list(fallback)


def extract_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError(f"LLM 没有返回 JSON:\n{text}")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError(f"LLM 返回的 JSON 不完整:\n{text}")


def call_llm_json(prompt: str) -> Dict[str, Any]:
    if client is None:
        raise RuntimeError("未配置 Foundry API，无法调用 LLM。")

    res = client.responses.create(model=MODEL_NAME, input=prompt)
    text = res.output_text.strip()
    return json.loads(extract_json_object(text))


def normalize_content_type(content_type: str, text: str = "", title: str = "") -> str:
    content_type = (content_type or "").strip()
    if content_type in CONTENT_TYPE_ENUMS:
        return content_type

    full_text = f"{title} {text}"
    if any(k in full_text for k in ["亲子", "遛娃", "小朋友", "儿童"]):
        return "family_guide"
    if any(k in full_text for k in ["商圈", "商场", "购物", "买手店"]):
        return "shopping_guide"
    if any(k in full_text for k in ["避坑", "踩雷", "不推荐", "别去"]):
        return "pitfall_warning"
    if any(k in full_text for k in ["地铁", "打车", "公交", "交通", "换乘"]):
        return "transport_tip"
    if any(k in full_text for k in ["预算", "人均", "门票", "省钱", "花费"]):
        return "budget_tip"
    if any(k in full_text for k in ["路线", "一日游", "二日游", "行程", "安排"]):
        return "route_plan"
    if any(k in full_text for k in ["小众", "冷门", "hidden"]):
        return "hidden_gem"
    if any(k in full_text for k in ["美食", "好吃", "餐厅", "小吃", "饭店"]):
        return "food_guide"
    return "attraction_guide"


def infer_districts(text: str, city: str) -> List[str]:
    found = re.findall(r"([\u4e00-\u9fa5]{1,12}(?:区|县|镇|街道|商圈))", text or "")
    cleaned = [x.strip() for x in found if x.strip() and x.strip() != city]
    return normalize_list(cleaned, fallback=[city], max_items=6)


def infer_time_suggestions(text: str) -> List[str]:
    out: List[str] = []
    if any(k in text for k in ["早上", "上午", "晨", "morning"]):
        out.append("morning")
    if any(k in text for k in ["中午", "午后", "下午", "afternoon"]):
        out.append("afternoon")
    if any(k in text for k in ["傍晚", "晚上", "夜景", "夜游", "evening", "night"]):
        out.append("evening")
    return out or ["morning", "afternoon"]


def infer_travel_type_tags(text: str, title: str = "") -> List[str]:
    full_text = f"{title} {text}"
    tags: List[str] = []
    mapping = {
        "family": ["亲子", "儿童", "小朋友", "遛娃"],
        "food": ["美食", "吃", "小吃", "餐厅"],
        "leisure": ["citywalk", "散步", "放松", "休闲", "拍照"],
        "nightlife": ["夜景", "夜游", "酒吧", "晚上"],
        "culture": ["博物馆", "历史", "寺庙", "古镇", "展览"],
        "shopping": ["商圈", "购物", "买手店", "商场"],
    }
    for tag, words in mapping.items():
        if any(w in full_text for w in words):
            tags.append(tag)
    return tags or ["leisure"]


def infer_poi_names(title: str, text: str, city: str) -> List[str]:
    candidates: List[str] = []
    patterns = [
        r"([\u4e00-\u9fa5A-Za-z0-9·]{2,20}(?:景区|景点|古镇|博物馆|公园|寺|街|巷子|商圈|广场|乐园|基地|塔|桥|山|湖))",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, f"{title} {text}"))

    cleaned = []
    for c in candidates:
        c = c.strip()
        if c and c != city and len(c) >= 2:
            cleaned.append(c)
    return normalize_list(cleaned, fallback=[], max_items=8)


def extract_post_metadata(title: str, context: str, city: str) -> Dict[str, Any]:
    if ENABLE_LLM_METADATA and client is not None:
        prompt = f"""
你是旅游内容结构化助手。请根据以下小红书帖子原文，为 RAG 检索生成 metadata。
只返回 JSON，不要输出别的内容。

城市：{city}
标题：{title}
正文：{context[:5000]}

返回格式必须严格如下：
{{
  "content_type": "attraction_guide",
  "tags": ["成都", "citywalk"],
  "poi_names": ["宽窄巷子"],
  "districts": ["青羊区"],
  "travel_type_tags": ["leisure"],
  "published_at": "",
  "price_level": "",
  "time_suggestions": ["afternoon"],
  "poi_types": ["街区"]
}}

要求：
1. content_type 只能从以下枚举选一个：
   attraction_guide, food_guide, route_plan, family_guide, hidden_gem, shopping_guide, local_tip, pitfall_warning, transport_tip, budget_tip
2. tags 返回 3-8 个
3. poi_names 返回正文里明确提到的 POI
4. districts 返回行政区/商圈，没有就空数组
5. travel_type_tags 可用 family/food/leisure/nightlife/culture/shopping
6. 没有信息就返回空字符串或空数组
"""
        try:
            data = call_llm_json(prompt)
            return {
                "content_type": normalize_content_type(data.get("content_type", ""), context, title),
                "tags": normalize_list(data.get("tags"), fallback=[city]),
                "poi_names": normalize_list(data.get("poi_names"), fallback=infer_poi_names(title, context, city)),
                "districts": normalize_list(data.get("districts"), fallback=infer_districts(context, city)),
                "travel_type_tags": normalize_list(data.get("travel_type_tags"), fallback=infer_travel_type_tags(context, title)),
                "published_at": str(data.get("published_at", "") or ""),
                "price_level": str(data.get("price_level", "") or ""),
                "time_suggestions": normalize_list(data.get("time_suggestions"), fallback=infer_time_suggestions(context)),
                "poi_types": normalize_list(data.get("poi_types"), fallback=[]),
            }
        except Exception as e:
            print(f"LLM metadata 抽取失败，改用规则兜底: {e}")

    return {
        "content_type": normalize_content_type("", context, title),
        "tags": normalize_list([city, title[:12], "小红书帖子"], fallback=[city]),
        "poi_names": infer_poi_names(title, context, city),
        "districts": infer_districts(context, city),
        "travel_type_tags": infer_travel_type_tags(context, title),
        "published_at": "",
        "price_level": "",
        "time_suggestions": infer_time_suggestions(context),
        "poi_types": [],
    }


def create_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument(f"--user-data-dir={CHROME_USER_DATA_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )
    return driver


def open_xhs_home_and_wait_login(driver: webdriver.Chrome) -> None:
    driver.get("https://www.xiaohongshu.com")
    print("已打开小红书首页，请手动登录。")
    input("登录完成后按回车继续...")


def open_search(driver: webdriver.Chrome, keyword: str) -> None:
    url = f"https://www.xiaohongshu.com/search_result?keyword={urllib.parse.quote(keyword)}"
    driver.get(url)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2.5)


def open_filter_panel(driver: webdriver.Chrome) -> None:
    wait = WebDriverWait(driver, 15)
    xpaths = [
        "//span[normalize-space(.)='筛选']",
        "//div[contains(@class,'filter')][.//span[normalize-space(.)='筛选']]",
        "//*[normalize-space(.)='筛选']",
    ]
    last_error: Optional[Exception] = None
    for xp in xpaths:
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(ACTION_SLEEP)
            return
        except Exception as e:
            last_error = e
    raise RuntimeError(f"无法打开筛选面板: {last_error}")


def try_click_content_type(driver: webdriver.Chrome, content_type: str = "图文") -> None:
    if content_type == "不限":
        return

    wait = WebDriverWait(driver, 10)
    xpaths = [
        f"//div[@id='image' and normalize-space(.)='{content_type}']",
        f"//div[contains(@class,'channel') and normalize-space(.)='{content_type}']",
        f"//span[normalize-space(.)='{content_type}']",
        f"//*[contains(@data-hp-kind,'filter-tag-{content_type}')]",
    ]
    for xp in xpaths:
        try:
            el = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            driver.execute_script("arguments[0].click();", el)
            time.sleep(ACTION_SLEEP)
            print(f"已点击内容类型: {content_type}")
            return
        except Exception:
            continue
    print(f"未找到内容类型按钮: {content_type}")


def try_click_sort_by(driver: webdriver.Chrome, sort_by: str = "最多收藏") -> None:
    wait = WebDriverWait(driver, 10)
    xpaths = [
        f"//div[contains(@data-hp-kind,'filter-tag-{sort_by}')]",
        f"//div[contains(@class,'tags') and .//span[normalize-space(.)='{sort_by}']]",
        f"//span[normalize-space(.)='{sort_by}']",
        f"//*[normalize-space(.)='{sort_by}']",
    ]
    for xp in xpaths:
        try:
            el = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            driver.execute_script("arguments[0].click();", el)
            time.sleep(ACTION_SLEEP)
            print(f"已点击排序方式: {sort_by}")
            return
        except Exception:
            continue
    print(f"未找到排序按钮: {sort_by}")


def apply_filters(driver: webdriver.Chrome, content_type: str = "图文", sort_by: str = "最多收藏") -> None:
    try:
        open_filter_panel(driver)
        try_click_content_type(driver, content_type)
        try_click_sort_by(driver, sort_by)
        time.sleep(2)
    except Exception as e:
        print(f"筛选操作出现问题，继续执行。错误: {e}")


def extract_xhs_note_id(url: str) -> str:
    if not url:
        return ""
    patterns = [
        r"/explore/([a-zA-Z0-9]+)",
        r"/discovery/item/([a-zA-Z0-9]+)",
        r"noteId=([a-zA-Z0-9]+)",
        r"source_id=([a-zA-Z0-9]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def extract_notes_from_page(driver: webdriver.Chrome) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(driver.page_source, "html.parser")
    notes: List[Dict[str, Any]] = []
    seen = set()

    for sec in soup.select("section.note-item"):
        a = sec.select_one("a.title") or sec.select_one("a[href*='/explore/']")
        if not a:
            continue

        href = a.get("href", "")
        title = normalize_whitespace(a.get_text(" ", strip=True))
        if not href:
            continue

        full_url = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}"
        note_id = extract_xhs_note_id(full_url)
        uniq = note_id or full_url
        if uniq in seen:
            continue
        seen.add(uniq)

        notes.append({
            "note_id": note_id,
            "title": title,
            "url": full_url,
        })
    return notes


def search_notes(driver: webdriver.Chrome, keyword: str, max_notes: int = MAX_NOTES, scroll_rounds: int = SCROLL_ROUNDS) -> List[Dict[str, Any]]:
    open_search(driver, keyword)
    apply_filters(driver, content_type="图文", sort_by="最多收藏")

    all_notes: Dict[str, Dict[str, Any]] = {}
    for i in range(scroll_rounds):
        notes = extract_notes_from_page(driver)
        for note in notes:
            key = note["note_id"] or note["url"]
            if key not in all_notes:
                note["search_rank"] = len(all_notes) + 1
                all_notes[key] = note

        print(f"滚动第 {i + 1} 轮，当前共 {len(all_notes)} 条")
        if len(all_notes) >= max_notes:
            break

        driver.execute_script("window.scrollBy(0, 1400)")
        time.sleep(2.2)

    return list(all_notes.values())[:max_notes]


def is_blocked_page(driver: webdriver.Chrome) -> bool:
    page_url = driver.current_url or ""
    page_text = normalize_whitespace(driver.page_source)
    blocked_signals = [
        "当前笔记暂时无法浏览",
        "请打开小红书App扫码查看",
        "当前笔记",
        "扫码查看",
    ]
    return "/404?" in page_url or any(s in page_text for s in blocked_signals)


def open_note_from_search_page(driver: webdriver.Chrome, note: Dict[str, Any]) -> bool:
    note_id = note.get("note_id", "")
    title = (note.get("title", "") or "").strip()
    wait = WebDriverWait(driver, OPEN_NOTE_WAIT)

    xpaths: List[str] = []
    if note_id:
        xpaths.extend([
            f"//a[contains(@href,'/explore/{note_id}')]",
            f"//a[contains(@href,'{note_id}')]",
        ])
    if title:
        esc = title.replace('"', "'")
        xpaths.extend([
            f"//a[contains(@class,'title') and normalize-space(.)=\"{esc}\"]",
            f"//a[contains(@class,'title') and contains(normalize-space(.), \"{esc[:20]}\")]",
        ])

    current_handles = set(driver.window_handles)

    for xp in xpaths:
        try:
            elem = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
            time.sleep(0.8)
            href = elem.get_attribute("href") or ""

            # 优先模拟 ctrl/cmd+点击，避免离开结果页。
            driver.execute_script("window.open(arguments[0], '_blank');", href)
            WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > len(current_handles))
            new_handles = [h for h in driver.window_handles if h not in current_handles]
            if new_handles:
                driver.switch_to.window(new_handles[-1])
                time.sleep(POST_READ_WAIT)
                return True
        except Exception:
            continue
    return False



def open_note_by_url(driver: webdriver.Chrome, note: Dict[str, Any]) -> bool:
    url = (note.get("url", "") or "").strip()
    if not url:
        return False
    try:
        driver.get(url)
        time.sleep(POST_READ_WAIT)
        return True
    except Exception as e:
        print(f"通过链接打开帖子失败: {url} | {e}")
        return False


def return_to_search_results(driver: webdriver.Chrome) -> None:
    try:
        driver.back()
        time.sleep(1.5)
    except Exception:
        pass
def close_note_tab_and_back_to_search(driver: webdriver.Chrome) -> None:
    if len(driver.window_handles) > 1:
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        time.sleep(1.5)


def clean_post_text(raw_text: str) -> str:
    text = normalize_whitespace(raw_text)

    warning_phrases = [
        "温馨提示 您的浏览器似乎开启了广告屏蔽插件，可能对正常使用造成影响，请移除插件或将小红书加入插件白名单后继续使用。",
        "您的浏览器似乎开启了广告屏蔽插件，可能对正常使用造成影响，请移除插件或将小红书加入插件白名单后继续使用。",
        "温馨提示",
        "我知道了",
        "请移除插件或将小红书加入插件白名单后继续使用",
        "广告屏蔽插件",
        "可能对正常使用造成影响",
    ]
    for phrase in warning_phrases:
        text = text.replace(phrase, " ")

    
    text = re.sub(
        r"(您的浏览器似乎开启了广告屏蔽插件，可能对正常使用造成影响，请移除插件或将小红书加入插件白名单后继续使用。\s*){1,}",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    
    text = re.sub(r"^.*?(?:笔记|正文|内容)", "", text, count=1) if len(text) > 500 else text

    
    parts = re.split(r"(?<=[。！？!?.])\s*", text)
    dedup_parts = []
    seen_recent = []
    for part in parts:
        p = normalize_whitespace(part)
        if not p:
            continue
        if p in seen_recent[-3:]:
            continue
        dedup_parts.append(p)
        seen_recent.append(p)

    text = " ".join(dedup_parts) if dedup_parts else text
    text = normalize_whitespace(text)
    text = text[:POST_TEXT_LIMIT]
    return text


def extract_post_text_from_note(driver: webdriver.Chrome, note: Dict[str, Any]) -> str:
    opened = open_note_by_url(driver, note)
    if not opened:
        print(f"无法通过链接进入帖子: {note.get('title', '')}")
        return ""

    try:
        if is_blocked_page(driver):
            print(f"帖子被拦截或网页端不可见: {note.get('title', '')}")
            return ""

        soup = BeautifulSoup(driver.page_source, "html.parser")

        
        text_parts: List[str] = []
        selectors = [
            "#detail-desc",
            ".note-content",
            ".desc",
            "[class*='content']",
            "[class*='desc']",
            "article",
            "main",
        ]
        for sel in selectors:
            for node in soup.select(sel):
                t = normalize_whitespace(node.get_text(" ", strip=True))
                if len(t) >= 20:
                    text_parts.append(t)

        raw_text = " ".join(text_parts) if text_parts else soup.get_text(" ", strip=True)
        return clean_post_text(raw_text)
    finally:
        return_to_search_results(driver)


def extract_post_title_from_note_text(note: Dict[str, Any], context: str) -> str:
    title = (note.get("title", "") or "").strip()
    if title:
        return title
    return context[:30]




def build_source_id(note: Dict[str, Any]) -> str:
    note_id = note.get("note_id", "") or extract_xhs_note_id(note.get("url", ""))
    if note_id:
        return note_id
    url = note.get("url", "")
    if url:
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    return hashlib.md5(str(time.time()).encode("utf-8")).hexdigest()[:12]


def build_chunk_id(source_id: str, chunk_index: int) -> str:
    return f"{source_id}_{chunk_index:03d}"


def split_text_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


def build_post_record(note: Dict[str, Any], city: str, context: str, rank: int, total: int) -> Dict[str, Any]:
    source_id = build_source_id(note)
    title = extract_post_title_from_note_text(note, context)
    metadata_base = extract_post_metadata(title, context, city)
    frequency = round(max(0.0, min(1.0, (total - rank + 1) / max(total, 1))), 4)

    chunks: List[Dict[str, Any]] = []
    for i, part in enumerate(split_text_into_chunks(context), start=1):
        metadata = {
            "source_id": source_id,
            "source_platform": "xiaohongshu",
            "title": title,
            "city": city,
            "content_type": metadata_base["content_type"],
            "tags": metadata_base["tags"],
            "poi_names": metadata_base["poi_names"],
            "districts": metadata_base["districts"],
            "travel_type_tags": metadata_base["travel_type_tags"],
            "published_at": metadata_base["published_at"],
            "chunk_index": i,
            "price_level": metadata_base["price_level"],
            "time_suggestions": metadata_base["time_suggestions"],
            "poi_types": metadata_base["poi_types"],
            "source_url": note.get("url", ""),
            "search_rank": rank,
        }
        chunks.append({
            "chunk_id": build_chunk_id(source_id, i),
            "source_id": source_id,
            "frequency": frequency,
            "context": part,
            "metadata": metadata,
        })

    return {
        "source_id": source_id,
        "title": title,
        "url": note.get("url", ""),
        "search_rank": rank,
        "frequency": frequency,
        "full_context": context,
        "metadata": {
            **metadata_base,
            "source_id": source_id,
            "source_platform": "xiaohongshu",
            "title": title,
            "city": city,
            "source_url": note.get("url", ""),
        },
        "chunks": chunks,
    }





def normalize_title_for_dedupe(title: str) -> str:
    title = normalize_whitespace(title).lower()
    title = re.sub(r"[^\w\u4e00-\u9fff]+", "", title)
    return title


def normalize_url_for_dedupe(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    url = url.split("?", 1)[0].rstrip("/")
    return url.lower()


def normalize_context_for_dedupe(text: str) -> str:
    text = normalize_whitespace(text)
    junk_patterns = [
        r"温馨提示",
        r"我知道了",
        r"您的浏览器似乎开启了广告屏蔽插件，可能对正常使用造成影响，请移除插件或将小红书加入插件白名单后继续使用。",
        r"请移除插件或将小红书加入插件白名单后继续使用",
        r"广告屏蔽插件",
    ]
    for pat in junk_patterns:
        text = re.sub(pat, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", "", text)
    return text


def deduplicate_notes(notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    搜索结果层去重：
    优先按 note_id，其次按规范化 url，最后按标题兜底。
    同一组里保留 search_rank 更靠前的一条。
    """
    best: Dict[str, Dict[str, Any]] = {}

    for idx, note in enumerate(notes, start=1):
        note_id = (note.get("note_id", "") or "").strip()
        url_key = normalize_url_for_dedupe(note.get("url", ""))
        title_key = normalize_title_for_dedupe(note.get("title", ""))

        if note_id:
            key = f"id::{note_id}"
        elif url_key:
            key = f"url::{url_key}"
        else:
            key = f"title::{title_key}"

        current_rank = int(note.get("search_rank", idx) or idx)
        note["search_rank"] = current_rank

        if key not in best:
            best[key] = note
            continue

        old_rank = int(best[key].get("search_rank", 10**9) or 10**9)
        if current_rank < old_rank:
            best[key] = note

    deduped = sorted(best.values(), key=lambda x: int(x.get("search_rank", 10**9) or 10**9))
    for i, note in enumerate(deduped, start=1):
        note["search_rank"] = i
    return deduped


def choose_better_post(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """
    重复帖子保留策略：
    1. 正文更长
    2. 搜索排名更靠前
    """
    a_len = len(normalize_context_for_dedupe(a.get("full_context", "")))
    b_len = len(normalize_context_for_dedupe(b.get("full_context", "")))
    if a_len != b_len:
        return a if a_len > b_len else b

    a_rank = int(a.get("search_rank", 10**9) or 10**9)
    b_rank = int(b.get("search_rank", 10**9) or 10**9)
    return a if a_rank <= b_rank else b


def deduplicate_posts_and_rebuild_chunks(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    最终输出层去重：
    - 先按 source_id 去重
    - 再按 标题 + 正文前 300 字 兜底去重
    - 去重后重建 chunks，避免残留重复 chunk
    """
    best_posts: Dict[str, Dict[str, Any]] = {}

    for post in posts:
        source_id = (post.get("source_id", "") or "").strip()
        title_key = normalize_title_for_dedupe(post.get("title", ""))
        context_key = normalize_context_for_dedupe(post.get("full_context", ""))[:300]

        if source_id:
            key = f"id::{source_id}"
        else:
            key = f"text::{title_key}::{context_key}"

        if key not in best_posts:
            best_posts[key] = post
        else:
            best_posts[key] = choose_better_post(best_posts[key], post)

    deduped_posts = list(best_posts.values())
    deduped_posts.sort(key=lambda x: int(x.get("search_rank", 10**9) or 10**9))

    rebuilt_posts: List[Dict[str, Any]] = []
    rebuilt_chunks: List[Dict[str, Any]] = []
    total = len(deduped_posts)

    for idx, post in enumerate(deduped_posts, start=1):
        post["search_rank"] = idx
        post["frequency"] = round(max(0.0, min(1.0, (total - idx + 1) / max(total, 1))), 4)

        source_id = post.get("source_id", "") or build_source_id({
            "note_id": post.get("source_id", ""),
            "url": post.get("url", "")
        })
        full_context = post.get("full_context", "") or ""
        rebuilt_post_chunks: List[Dict[str, Any]] = []

        for chunk_index, part in enumerate(split_text_into_chunks(full_context), start=1):
            metadata = dict(post.get("metadata", {}) or {})
            metadata.update({
                "source_id": source_id,
                "source_platform": "xiaohongshu",
                "title": post.get("title", ""),
                "city": metadata.get("city", ""),
                "source_url": post.get("url", ""),
                "chunk_index": chunk_index,
                "search_rank": idx,
            })

            chunk = {
                "chunk_id": build_chunk_id(source_id, chunk_index),
                "source_id": source_id,
                "frequency": post["frequency"],
                "context": part,
                "metadata": metadata,
            }
            rebuilt_post_chunks.append(chunk)
            rebuilt_chunks.append(chunk)

        post["chunks"] = rebuilt_post_chunks
        rebuilt_posts.append(post)

    return {
        "posts": rebuilt_posts,
        "chunks": rebuilt_chunks,
    }



def build_retrieval_chunks_from_posts(driver: webdriver.Chrome, notes: List[Dict[str, Any]], city: str) -> Dict[str, Any]:
    posts: List[Dict[str, Any]] = []
    chunks: List[Dict[str, Any]] = []
    total = len(notes)

    for idx, note in enumerate(notes, start=1):
        print(f"\n[{idx}/{total}] 读取帖子: {note.get('title', '')}")
        context = extract_post_text_from_note(driver, note)
        if len(context) < MIN_CONTEXT_LEN:
            print("正文过短或未读取到，跳过。")
            time.sleep(2.0)
            continue

        record = build_post_record(note, city, context, idx, total)
        posts.append(record)
        chunks.extend(record["chunks"])
        time.sleep(2.5)

    return {
        "posts": posts,
        "chunks": chunks,
    }


def generate_travel_retrieval(city: str) -> str:
    if not city or not city.strip():
        raise ValueError("city 不能为空")

    city = city.strip()
    ensure_directories()
    driver = create_driver()

    try:
        open_xhs_home_and_wait_login(driver)
        keyword = f"{city}旅游攻略"
        print(f"\n正在搜索: {keyword}")

        notes = search_notes(driver, keyword)
        print(f"共抓到 {len(notes)} 条搜索结果")

        notes = deduplicate_notes(notes)
        print(f"搜索结果去重后剩余 {len(notes)} 条")

        if not notes:
            raise RuntimeError("没有抓到任何帖子，请检查登录状态、页面结构或筛选按钮。")

        result = build_retrieval_chunks_from_posts(driver, notes, city)

        cleaned_result = deduplicate_posts_and_rebuild_chunks(result["posts"])
        posts = cleaned_result["posts"]
        chunks = cleaned_result["chunks"]

        print(f"最终去重后保留 {len(posts)} 篇帖子，生成 {len(chunks)} 个 chunks")
        if not chunks:
            raise RuntimeError("没有抓到可用帖子正文。当前很可能被网页端风控或帖子无法在网页端查看。")

        city_safe = safe_filename(city)
        raw_notes_path = os.path.join(OUTPUT_DIR, f"{city_safe}_raw_notes.json")
        
        for post in posts:
            post["full_context"] = clean_post_text(post.get("full_context", ""))
            if "chunks" in post and isinstance(post["chunks"], list):
                for ch in post["chunks"]:
                    ch["context"] = clean_post_text(ch.get("context", ""))

        for ch in chunks:
            ch["context"] = clean_post_text(ch.get("context", ""))

        posts_path = os.path.join(OUTPUT_DIR, f"{city_safe}_posts.json")
        chunks_json_path = os.path.join(OUTPUT_DIR, f"{city_safe}_retrieval_chunks.json")
        chunks_csv_path = os.path.join(OUTPUT_DIR, f"{city_safe}_retrieval_chunks.csv")

        save_json(notes, raw_notes_path)
        save_json(posts, posts_path)
        save_json(chunks, chunks_json_path)
        save_csv(chunks, chunks_csv_path)

        print(f"\n✅ 搜索结果: {raw_notes_path}")
        print(f"✅ 帖子级原文: {posts_path}")
        print(f"✅ RAG JSON: {chunks_json_path}")
        print(f"✅ RAG CSV: {chunks_csv_path}")
        return chunks_json_path
    finally:
        driver.quit()


if __name__ == "__main__":
    city_input = input("请输入城市名: ").strip()
    output_path = generate_travel_retrieval(city_input)
    print(f"最终输出文件: {output_path}")
