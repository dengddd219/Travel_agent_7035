"""
C组统一旅行信息API模块
作者: Yufei Kang

包含天气、酒店、机票、费用四个功能

天气来源: 高德地图AMAP
机票来源: 携程机票API
酒店来源: 飞猪/淘宝酒店API


开放能力概览
依托飞猪 AI 开放平台，开发者可以一键接入全品类旅游生态，本期 Skill 开放聚焦搜索维度，重点推出以下两类核心能力，赋能智慧旅行应用的构建。

1. 全域搜索
利用自然语言处理技术，实现一键式跨品类搜索。

服务范围： 酒店、机票、景点门票、度假等场景全覆盖。

2. 垂直场景搜索引擎
酒店搜索 ： 涵盖全球海量酒店、度假村、民宿及高端酒店套餐。
机票搜索： 实时查询全球航班动态，支持复杂航程对比。
POI搜索： 提供景点门票预订、周边一日游、境外签证办理及当地向导服务。

"""

import hashlib
import html
import json
import os
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    sync_playwright = None
    PlaywrightTimeoutError = Exception
    PLAYWRIGHT_AVAILABLE = False

CITY_TO_CTRIP_CODE = {
    '北京': 'BJS', '上海': 'SHA', '广州': 'CAN', '深圳': 'SZX', '成都': 'CTU',
    '杭州': 'HGH', '武汉': 'WUH', '西安': 'SIA', '重庆': 'CKG', '青岛': 'TAO',
    '长沙': 'CSX', '南京': 'NKG', '厦门': 'XMN', '昆明': 'KMG', '大连': 'DLC',
    '天津': 'TSN', '郑州': 'CGO', '三亚': 'SYX', '济南': 'TNA', '福州': 'FOC',
    '南宁': 'NNG', '贵阳': 'KWE', '桂林': 'KWL', '海口': 'HAK', '哈尔滨': 'HRB',
    '沈阳': 'SHE', '长春': 'CGQ', '石家庄': 'SJW', '兰州': 'LHW', '乌鲁木齐': 'URC',
    '呼和浩特': 'HET', '银川': 'INC', '拉萨': 'LXA', '西宁': 'XNN', '南昌': 'KHN',
    '惠州': 'HUZ', '烟台': 'YNT', '威海': 'WEH', '无锡': 'WUX', '苏州': 'WUX',
    '常州': 'CZX', '南通': 'NTG', '扬州': 'YTY', '镇江': 'ZHA', '徐州': 'XUZ',
    '连云港': 'LYG', '盐城': 'YNZ', '淮安': 'HIA', '宿迁': 'XUZ', '泰州': 'YTY',
    '合肥': 'HFE', '芜湖': 'WUH', '蚌埠': 'HFE', '安庆': 'AQG', '黄山': 'TXN',
    '阜阳': 'FUG', '淮南': 'HFE', '滁州': 'HFE', '马鞍山': 'HFE', '六安': 'TXN',
    '宣城': 'TXN', '铜陵': 'HFE', '池州': 'JUH', '亳州': 'BGS', '宿州': 'SYS',
    '绵阳': 'MIG', '德阳': 'DAX', '南充': 'NAO', '宜宾': 'YBP', '泸州': 'LZO',
    '达州': 'DAX', '雅安': 'YAC', '眉山': 'MIG', '资阳': 'CIF', '广元': 'GYS',
    '攀枝花': 'PZI', '巴中': 'BZX', '凉山': 'LJG', '阿坝': 'NGQ', '甘孜': 'DAX',
    '哈密': 'HMI', '吐鲁番': 'TLQ', '伊宁': 'YIN', '兰州': 'LHW', '嘉峪关': 'JGN',
    '敦煌': 'DNH', '临沧': 'LNJ', '丽江': 'LJG', '西双版纳': 'JHG', '保山': 'BSD',
    '曲靖': 'KMG', '文山': 'WNH', '昭通': 'ZAT', '玉树': 'YUS', '阿勒泰': 'AAT',
    '额济纳旗': 'EJN', '喀什': 'KHG', '库尔勒': 'KRL', '阿克苏': 'AKU', '库车': 'KCA',
    '乌拉特中旗': 'WZQ', '西昌': 'XIC', '海拉尔': 'HLD', '锦州': 'JNZ', '营口': 'YKH',
    '大庆': 'DQA', '牡丹江': 'MDG', '佳木斯': 'JMU', '鹤岗': 'HGH', '双鸭山': 'SYA',
    '大同': 'DAT', '晋中': 'JIC', '临汾': 'LFQ', '运城': 'YCU', '朔州': 'SZH',
    '忻州': 'WUT', '吕梁': 'LLV', '阳泉': 'YIQ', '长治': 'CIH', '晋城': 'JNG',
    '十堰': 'WDS', '宜昌': 'YIH', '襄阳': 'XFN', '荆州': 'SHS', '荆门': 'JM1',
    '恩施': 'ENH', '潜江': 'HJJ', '天门': 'WUT', '仙桃': 'WUT', '随州': 'WUT'
}

DEFAULT_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Referer": "https://www.ctrip.com/"
}


def _load_local_env(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        print(f"读取本地环境变量文件失败: {exc}")


_load_local_env()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _decode_js_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value


def _normalize_price(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    return float(match.group())


def _build_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HTTP_HEADERS)
    return session


def _build_date_range(start_date: str, end_date: str) -> List[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if end < start:
        raise ValueError("返程日期不能早于去程日期")

    current = start
    dates = []
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def _extract_escaped_json_object(text: str, marker: str) -> Optional[Dict]:
    idx = text.find(marker)
    if idx == -1:
        return None

    start = text.find("{", idx)
    if start == -1:
        return None

    in_string = False
    escape = False
    depth = 0
    end = None

    for pos in range(start, len(text)):
        char = text[pos]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break

    if end is None:
        return None

    fragment = text[start:end]
    try:
        decoded = json.loads(f'"{fragment}"')
        return json.loads(decoded)
    except Exception:
        return None


def _fetch_page_html_with_playwright(url: str, headless: bool = True,
                                     wait_selectors: Optional[List[str]] = None,
                                     wait_ms: int = 4000) -> Optional[str]:
    if not PLAYWRIGHT_AVAILABLE or sync_playwright is None:
        return None

    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                user_agent=DEFAULT_HTTP_HEADERS["User-Agent"],
                locale="zh-CN",
                viewport={"width": 1440, "height": 1200}
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            for selector in wait_selectors or []:
                try:
                    page.wait_for_selector(selector, timeout=5000)
                    break
                except PlaywrightTimeoutError:
                    continue

            page.wait_for_timeout(wait_ms)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
            page.wait_for_timeout(1000)
            content = page.content()
            context.close()
            browser.close()
            return content
    except Exception as exc:
        short_error = str(exc).split("Call log:", 1)[0].strip()
        short_error = short_error.split("Browser logs:", 1)[0].strip()
        print(f"Playwright 打开页面失败: {short_error}")
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        return None


class HotelAPI:
    """酒店查询与详情API"""

    def __init__(self):
        self.feizhu_api_key = os.getenv('FEIZHU_API_KEY')
        self.feizhu_api_url = os.getenv('FEIZHU_API_URL', 'https://openapi.fliggy.com/hotel/search')
        self.app_key = os.getenv('TAOBAO_APP_KEY', 'your_app_key')
        self.app_secret = os.getenv('TAOBAO_APP_SECRET', 'your_app_secret')
        self.session_key = os.getenv('TAOBAO_SESSION_KEY', 'your_session_key')
        self.target_app_key = os.getenv('TAOBAO_TARGET_APP_KEY')
        self.base_url = 'https://eco.taobao.com/router/rest'
        self.allow_mock_data = _env_flag('ALLOW_MOCK_DATA', True)
        self.use_playwright_scraper = _env_flag('USE_PLAYWRIGHT_SCRAPER', True)
        self.playwright_headless = _env_flag('PLAYWRIGHT_HEADLESS', True)
        self.use_persistent_login_context = _env_flag('USE_PERSISTENT_LOGIN_CONTEXT', True)
        self.ctrip_manual_login_on_start = _env_flag('CTRIP_MANUAL_LOGIN_ON_START', False)
        self.playwright_user_data_dir = os.getenv(
            'PLAYWRIGHT_USER_DATA_DIR',
            os.path.join('.playwright', 'ctrip-user-data')
        )
        self.hotel_entry_url = os.getenv(
            'CTRIP_HOTEL_ENTRY_URL',
            'https://hotels.ctrip.com/?allianceid=4899&sid=963772'
        )
        self.session = _build_http_session()

    def _sign_taobao_request(self, params: Dict) -> str:
        sign_base = self.app_secret + ''.join(
            f'{key}{params[key]}' for key in sorted(params)
        ) + self.app_secret
        return hashlib.md5(sign_base.encode('utf-8')).hexdigest().upper()

    def _call_feizhu_api(self, params: Dict) -> Dict:
        if not self.feizhu_api_key or not self.feizhu_api_url:
            return {}

        headers = {
            'x-api-key': self.feizhu_api_key,
            'Accept': 'application/json'
        }
        params = {
            **params,
            'app_key': self.feizhu_api_key,
            'format': 'json'
        }

        try:
            response = requests.get(self.feizhu_api_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and result.get('error'):
                print(f"飞猪API错误: {result.get('error')}")
                return {}
            return result
        except Exception as e:
            print(f"调用飞猪API失败: {e}")
            return {}

    def _call_taobao_api(self, method: str, params: Dict) -> Dict:
        request_params = {
            'method': method,
            'app_key': self.app_key,
            'session': self.session_key,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'format': 'json',
            'v': '2.0',
            'sign_method': 'md5',
            **params
        }
        if self.target_app_key:
            request_params['target_app_key'] = self.target_app_key
        request_params['sign'] = self._sign_taobao_request(request_params)
        try:
            response = requests.post(self.base_url, data=request_params, timeout=30)
            response.raise_for_status()
            result = response.json()
            if 'error_response' in result:
                print(f"淘宝API错误: {result['error_response']}")
                return {}
            return result
        except Exception as e:
            print(f"调用淘宝API失败: {e}")
            return {}

    def search_hotels(self, city: str, check_in_date: str, check_out_date: str,
                      keyword: Optional[str] = None, star_rate: Optional[int] = None) -> List[Dict]:
        scraped_hotels = self._scrape_ctrip_hotels(city, check_in_date, check_out_date, keyword, star_rate)
        if scraped_hotels:
            return scraped_hotels

        print("未抓到携程酒店实时价格，预算将使用本地城市住宿参考价")
        return []

    def _scrape_ctrip_hotels(self, city: str, check_in_date: str, check_out_date: str,
                             keyword: Optional[str] = None, star_rate: Optional[int] = None) -> List[Dict]:
        keyword_value = keyword or city
        urls = self._build_ctrip_hotel_result_urls(city, check_in_date, check_out_date, keyword_value)

        if self.use_playwright_scraper:
            for url in urls:
                html = self._fetch_ctrip_hotel_results_via_playwright(
                    city=city,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    result_url=url
                )
                if html:
                    hotels = self._extract_hotels_from_html(
                        html, city, star_rate=star_rate, source_url=url
                    )
                    if hotels:
                        for hotel in hotels:
                            hotel["source"] = "hotel_playwright_scraper"
                        return hotels

            # City mismatch likely caused by stale persistent session cookie.
            # Retry once with a fresh non-persistent context to bypass the stale state.
            if self.use_persistent_login_context:
                print("携程持久化 session 城市不一致，尝试无持久化 context 重试…")
                original_flag = self.use_persistent_login_context
                self.use_persistent_login_context = False
                try:
                    for url in urls:
                        html = self._fetch_ctrip_hotel_results_via_playwright(
                            city=city,
                            check_in_date=check_in_date,
                            check_out_date=check_out_date,
                            result_url=url
                        )
                        if html:
                            hotels = self._extract_hotels_from_html(
                                html, city, star_rate=star_rate, source_url=url
                            )
                            if hotels:
                                for hotel in hotels:
                                    hotel["source"] = "hotel_playwright_scraper"
                                return hotels
                finally:
                    self.use_persistent_login_context = original_flag

        self._warm_ctrip_hotel_session()
        for url in urls:
            try:
                response = self.session.get(
                    url,
                    timeout=20,
                    headers={"Referer": self.hotel_entry_url, **DEFAULT_HTTP_HEADERS}
                )
                response.raise_for_status()
                hotels = self._extract_hotels_from_html(
                    response.text, city, star_rate=star_rate, source_url=url
                )
                if hotels:
                    return hotels
            except Exception as e:
                print(f"抓取携程酒店页面失败: {e}")

        return []

    def _build_ctrip_hotel_result_urls(self, city: str, check_in_date: str,
                                       check_out_date: str, keyword_value: str) -> List[str]:
        city_code = CITY_TO_CTRIP_CODE.get(city, "")
        base = (
            "https://hotels.ctrip.com/hotels/list"
            f"?cityName={quote(city)}&checkin={check_in_date}&checkout={check_out_date}"
            f"&keyword={quote(keyword_value)}"
        )
        if city_code:
            base += f"&cityCode={city_code}"
        return [base]

    def _warm_ctrip_hotel_session(self) -> None:
        try:
            self.session.get(self.hotel_entry_url, timeout=15)
        except Exception as exc:
            print(f"预热携程酒店入口页失败: {exc}")

    def prepare_ctrip_login_session(self) -> bool:
        if not PLAYWRIGHT_AVAILABLE or sync_playwright is None:
            print("Playwright is not available for manual Ctrip login.")
            return False

        if self.playwright_headless:
            print("Set PLAYWRIGHT_HEADLESS=false before preparing a manual login session.")
            return False

        os.makedirs(self.playwright_user_data_dir, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=self.playwright_user_data_dir,
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                    user_agent=DEFAULT_HTTP_HEADERS["User-Agent"],
                    locale="zh-CN",
                    viewport={"width": 1440, "height": 1200}
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                page.goto(self.hotel_entry_url, wait_until="domcontentloaded", timeout=30000)
                print("Please log in to your Ctrip account in the opened browser, then press Enter here to continue...")
                input()
                context.close()
            return True
        except Exception as exc:
            short_error = str(exc).split("Call log:", 1)[0].strip()
            print(f"Failed to prepare manual Ctrip login session: {short_error}")
            return False

    def _fetch_ctrip_hotel_results_via_playwright(self, city: str, check_in_date: str,
                                                  check_out_date: str,
                                                  result_url: str) -> Optional[str]:
        if not PLAYWRIGHT_AVAILABLE or sync_playwright is None:
            return None

        browser = None
        context = None
        try:
            with sync_playwright() as playwright:
                if self.use_persistent_login_context:
                    os.makedirs(self.playwright_user_data_dir, exist_ok=True)
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=self.playwright_user_data_dir,
                        headless=self.playwright_headless,
                        args=["--disable-blink-features=AutomationControlled"],
                        user_agent=DEFAULT_HTTP_HEADERS["User-Agent"],
                        locale="zh-CN",
                        viewport={"width": 1440, "height": 1200}
                    )
                else:
                    browser = playwright.chromium.launch(
                        headless=self.playwright_headless,
                        args=["--disable-blink-features=AutomationControlled"]
                    )
                    context = browser.new_context(
                        user_agent=DEFAULT_HTTP_HEADERS["User-Agent"],
                        locale="zh-CN",
                        viewport={"width": 1440, "height": 1200}
                    )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                page.goto(self.hotel_entry_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                if self.ctrip_manual_login_on_start and not self.playwright_headless:
                    print("Confirm the Ctrip account is logged in within the opened browser, then press Enter to continue...")
                    input()
                self._prepare_ctrip_hotel_search_context(
                    page,
                    city,
                    allow_failure=self.use_persistent_login_context
                )
                page.goto(result_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(6000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.4)")
                page.wait_for_timeout(1500)
                content = page.content()
                context.close()
                if browser is not None:
                    browser.close()
                return content
        except Exception as exc:
            short_error = str(exc).split("Call log:", 1)[0].strip()
            short_error = short_error.split("Browser logs:", 1)[0].strip()
            print(f"Playwright 酒店入口页抓取失败: {short_error}")
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            return None

    def _prepare_ctrip_hotel_search_context(self, page, city: str, allow_failure: bool = False) -> None:
        input_selectors = [
            'input[placeholder="目的地"]',
            '#destinationInput'
        ]

        destination_input = None
        for selector in input_selectors:
            locator = page.locator(selector)
            if locator.count() > 0:
                destination_input = locator.first
                break

        if destination_input is None:
            return

        try:
            destination_input.click(timeout=5000)
            page.wait_for_timeout(300)
            destination_input.press("Control+A")
            destination_input.fill(city)
            page.wait_for_timeout(1200)

            suggestion_selectors = [
                f'[role="option"]:has-text("{city}")',
                f'text="{city}"'
            ]
            selected = False
            for selector in suggestion_selectors:
                suggestion = page.locator(selector)
                if suggestion.count() > 0:
                    suggestion.first.click(timeout=3000)
                    selected = True
                    break

            if not selected:
                destination_input.press("Enter")
            page.wait_for_timeout(1200)
        except Exception as exc:
            short_error = str(exc).split("Call log:", 1)[0].strip()
            if allow_failure:
                print(f"携程入口页的目的地输入未完成，将直接访问搜索结果页: {short_error}")
            else:
                print(f"设置携程酒店目的地失败: {short_error}")

    def _extract_hotels_from_html(self, html: str, city: str,
                                  star_rate: Optional[int] = None,
                                  source_url: Optional[str] = None) -> List[Dict]:
        result_city = self._extract_result_city_from_html(html)
        if result_city and city not in result_city and result_city not in city:
            print(f"携程酒店页面返回城市为 {result_city}，与请求城市 {city} 不一致，已放弃本次结果")
            return []

        hotels_from_init = self._extract_hotels_from_init_data(
            html, city=city, star_rate=star_rate, source_url=source_url
        )
        if hotels_from_init:
            return hotels_from_init

        hotels = []
        seen_keys = set()
        patterns = [
            re.compile(
                r'"hotelId"\s*:\s*"?(?P<hotel_id>\d+)"?.{0,800}?'
                r'"hotelName"\s*:\s*"(?P<name>[^"]+)".{0,800}?'
                r'"(?:price|minPrice|salePrice|displayPrice|startPrice)"\s*:\s*"?(?P<price>\d+(?:\.\d+)?)"?',
                re.S
            ),
            re.compile(
                r'"hotelName"\s*:\s*"(?P<name>[^"]+)".{0,800}?'
                r'"(?:price|minPrice|salePrice|displayPrice|startPrice)"\s*:\s*"?(?P<price>\d+(?:\.\d+)?)"?',
                re.S
            )
        ]

        for pattern in patterns:
            for match in pattern.finditer(html):
                hotel_id = match.groupdict().get("hotel_id")
                name = _decode_js_string(match.group("name"))
                price = _normalize_price(match.group("price"))
                if not name or price is None:
                    continue
                if star_rate and str(star_rate) not in html[max(0, match.start() - 200): match.end() + 200]:
                    continue

                dedupe_key = hotel_id or name
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                address_match = re.search(
                    r'"address"\s*:\s*"([^"]+)"',
                    html[match.start(): min(len(html), match.end() + 500)]
                )
                district_match = re.search(
                    r'"district"\s*:\s*"([^"]+)"',
                    html[match.start(): min(len(html), match.end() + 500)]
                )

                hotels.append({
                    "hotel_id": hotel_id or f"scraper_{len(hotels) + 1}",
                    "name": name,
                    "address": _decode_js_string(address_match.group(1)) if address_match else None,
                    "city": city,
                    "district": _decode_js_string(district_match.group(1)) if district_match else None,
                    "business": None,
                    "star_rate": star_rate,
                    "min_price": int(price) if float(price).is_integer() else price,
                    "max_price": None,
                    "available": True,
                    "source": "hotel_scraper",
                    "source_url": source_url
                })

                if len(hotels) >= 20:
                    return hotels

        return hotels

    def _extract_result_city_from_html(self, html_text: str) -> Optional[str]:
        # 属性顺序不固定，先整体匹配 input 标签，再从中提取 value
        tag_match = re.search(r'<input[^>]*id="destinationInput"[^>]*/?>',  html_text)
        if tag_match:
            value_match = re.search(r'value="([^"]+)"', tag_match.group(0))
            if value_match:
                return html.unescape(value_match.group(1)).strip()
        return None

    def _extract_init_data_from_next_data(self, html_text: str) -> Optional[Dict]:
        match = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>\s*(\{.+?\})\s*</script>',
            html_text,
            re.S
        )
        if not match:
            return None
        try:
            next_data = json.loads(match.group(1))
        except Exception:
            return None

        # 在 props/pageProps 树里找 initListData 或 hotelList
        def _deep_find(obj, targets):
            if isinstance(obj, dict):
                for key in targets:
                    if key in obj:
                        return obj[key]
                for value in obj.values():
                    result = _deep_find(value, targets)
                    if result is not None:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = _deep_find(item, targets)
                    if result is not None:
                        return result
            return None

        init_list = _deep_find(next_data, ("initListData",))
        if isinstance(init_list, dict):
            return init_list
        hotel_list = _deep_find(next_data, ("hotelList",))
        if isinstance(hotel_list, list):
            return {"hotelList": hotel_list}
        return None

    def _extract_hotels_from_init_data(self, html_text: str, city: str,
                                       star_rate: Optional[int] = None,
                                       source_url: Optional[str] = None) -> List[Dict]:
        # 优先尝试 Next.js 标准注水格式 __NEXT_DATA__
        init_data = self._extract_init_data_from_next_data(html_text)
        # 回退到原有双重转义 JSON 格式
        if not init_data:
            init_data = _extract_escaped_json_object(html_text, '\\"initListData\\":')
        if not init_data or not isinstance(init_data, dict):
            return []

        hotel_list = init_data.get("hotelList") or []
        hotels = []
        for item in hotel_list:
            hotel_info = item.get("hotelInfo") or {}
            summary = hotel_info.get("summary") or {}
            name_info = hotel_info.get("nameInfo") or {}
            position_info = hotel_info.get("positionInfo") or {}
            comment_info = hotel_info.get("commentInfo") or {}
            sign_in_note = hotel_info.get("signInNote") or {}
            hotel_star = hotel_info.get("hotelStar") or {}
            room_info_list = item.get("roomInfo") or []
            first_room = room_info_list[0] if room_info_list else {}
            room_summary = first_room.get("summary") or {}

            hotel_name = (
                (name_info.get("names") or [None])[0]
                or name_info.get("name")
            )
            hotel_id = summary.get("hotelId") or summary.get("masterHotelId")
            current_star = hotel_star.get("star")
            if star_rate and current_star and int(current_star) != int(star_rate):
                continue

            position_desc = position_info.get("positionDesc")
            address = position_info.get("address")
            zones = position_info.get("zoneNames") or []
            hotel = {
                "hotel_id": hotel_id,
                "name": hotel_name,
                "address": address or position_desc,
                "city": position_info.get("cityName") or city,
                "district": zones[0] if zones else None,
                "business": position_desc,
                "star_rate": current_star,
                "min_price": self._extract_visible_price_from_html_card(html_text, hotel_id),
                "max_price": None,
                "available": True,
                "source": "hotel_init_data",
                "source_url": source_url,
                "comment_score": comment_info.get("commentScore"),
                "comment_desc": comment_info.get("commentDescription"),
                "comment_num": comment_info.get("commenterNumber"),
                "room_name": room_summary.get("saleRoomName"),
                "price_note": html.unescape(sign_in_note.get("title", "")).replace("{0}", "").replace("{/0}", "")
            }
            hotels.append(hotel)
            if len(hotels) >= 20:
                break

        return hotels

    def _extract_visible_price_from_html_card(self, html_text: str, hotel_id: Optional[str]) -> Optional[float]:
        if not hotel_id:
            return None

        marker = f'<div class="hotel-card" id="{hotel_id}"'
        start = html_text.find(marker)
        if start == -1:
            marker = f'data-offline-hotelId="{hotel_id}"'
            start = html_text.find(marker)
            if start == -1:
                return None

        next_idx = html_text.find('<div class="list-item">', start + 1)
        segment = html_text[start: next_idx if next_idx != -1 else min(len(html_text), start + 12000)]

        focused_segments = []
        for anchor in ['room-price', 'price-line', 'price-wrap', 'price_box', 'salePrice', 'displayPrice', 'startPrice']:
            idx = segment.find(anchor)
            if idx != -1:
                focused_segments.append(segment[max(0, idx - 120): min(len(segment), idx + 600)])

        price_patterns = [
            r'(?:salePrice|displayPrice|startPrice|minPrice|price)\D{0,20}([1-9]\d{1,4}(?:\.\d{1,2})?)',
            r'([1-9]\d{1,4}(?:\.\d{1,2})?)\s*元',
            r'¥\s*([1-9]\d{1,4}(?:\.\d{1,2})?)',
            r'￥\s*([1-9]\d{1,4}(?:\.\d{1,2})?)'
        ]
        candidate_segments = focused_segments or [segment]
        for candidate_segment in candidate_segments:
            for pattern in price_patterns:
                for match in re.finditer(pattern, candidate_segment, re.I):
                    price = _normalize_price(match.group(1))
                    if price is not None and price >= 50:
                        return price
        return None

    def get_hotel_info(self, hotel_id: str) -> Dict:
        return {
            'hotel_id': hotel_id,
            'name': None,
            'address': None,
            'city': None,
            'district': None,
            'business': None,
            'star_rate': None,
            'service': [],
            'facility': [],
            'description': '酒店详情开放平台接口不可用，当前版本未抓取详情页。',
            'images': [],
            'longitude': None,
            'latitude': None,
            'source': 'hotel_scraper_placeholder'
        }

    def get_hotel_room_types(self, hotel_id: str, room_type_id: Optional[str] = None,
                              outer_id: Optional[str] = None, vendor: str = 'taobao') -> List[Dict]:
        return []

    def get_hotel_rates(self, hotel_id: str, check_in_date: str, check_out_date: str,
                        room_type_id: Optional[str] = None) -> List[Dict]:
        return []

    def get_hotel_availability(self, hotel_id: str, check_in_date: str, check_out_date: str) -> Dict:
        return {
            'hotel_id': hotel_id,
            'check_in_date': check_in_date,
            'check_out_date': check_out_date,
            'available': None,
            'room_types': [],
            'source': 'hotel_scraper_placeholder'
        }

    def get_hotel_details(self, hotel_id: str, check_in_date: str, check_out_date: str) -> Dict:
        hotel_info = self.get_hotel_info(hotel_id)
        room_types = self.get_hotel_room_types(hotel_id)
        rates = self.get_hotel_rates(hotel_id, check_in_date, check_out_date)
        availability = self.get_hotel_availability(hotel_id, check_in_date, check_out_date)
        return {
            'hotel': hotel_info,
            'room_types': room_types,
            'rates': rates,
            'availability': availability,
            'source': 'hotel_scraper_placeholder'
        }


class WeatherCostAPI:
    """天气、费用与酒店整合API"""

    def __init__(self):
        self.city_cost_data = self._load_city_cost_reference()
        self.hotel_api = HotelAPI()
        self.allow_mock_data = _env_flag('ALLOW_MOCK_DATA', True)
        self.use_playwright_scraper = _env_flag('USE_PLAYWRIGHT_SCRAPER', True)
        self.playwright_headless = _env_flag('PLAYWRIGHT_HEADLESS', True)
        self.session = _build_http_session()

    def get_provider_status(self) -> Dict:
        return {
            "weather": {
                "provider": "amap",
                "configured": bool(os.getenv("AMAP_WEB_SERVICE_KEY")),
                "base_url": "https://restapi.amap.com/v3/weather/weatherInfo"
            },
            "hotel": {
                "provider": "ctrip_hotel_scraper",
                "configured": True,
                "platform_api_enabled": False,
                "playwright_available": PLAYWRIGHT_AVAILABLE,
                "use_playwright_scraper": self.use_playwright_scraper,
                "note": "淘宝/天猫/飞猪开放平台酒店接口已停用，当前使用携程页面抓取、Playwright 和模拟数据"
            },
            "flight": {
                "provider": "ctrip_flight_scraper",
                "configured": True,
                "playwright_available": PLAYWRIGHT_AVAILABLE,
                "use_playwright_scraper": self.use_playwright_scraper,
                "note": "当前优先使用 Playwright 打开携程页面抓价格，失败时退回 requests 解析"
            },
            "runtime": {
                "allow_mock_data": self.allow_mock_data
            }
        }

    def get_flight_price(self, dcity: str, acity: str, flight_way: str = "Oneway",
                         direct: bool = True, army: bool = False,
                         travel_date: Optional[str] = None) -> Dict:
        """抓取公开页面中的机票最低价格，可按指定日期查询"""
        departure_code = CITY_TO_CTRIP_CODE.get(dcity)
        arrival_code = CITY_TO_CTRIP_CODE.get(acity)
        if not departure_code or not arrival_code:
            return {
                "error": "不支持的城市名称，请使用支持的中文城市名称，例如 北京/上海/广州/深圳/成都/杭州/武汉/西安/重庆/南宁",
                "departure_code": departure_code,
                "arrival_code": arrival_code
            }

        requested_date = None
        if travel_date:
            requested_date = travel_date.replace('-', '')
            if len(requested_date) != 8 or not requested_date.isdigit():
                return {
                    "error": "travel_date 格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD",
                    "travel_date": travel_date
                }
        else:
            travel_date = datetime.now().strftime("%Y-%m-%d")
            requested_date = travel_date.replace("-", "")

        scraped = self._scrape_ctrip_flight_price(
            dcity=dcity,
            acity=acity,
            departure_code=departure_code,
            arrival_code=arrival_code,
            flight_way=flight_way,
            direct=direct,
            army=army,
            travel_date=travel_date,
            requested_date=requested_date
        )
        if scraped:
            return scraped

        url = "https://flights.ctrip.com/itinerary/api/12808/lowestPrice"
        params = {
            "flightWay": flight_way,
            "dcity": departure_code,
            "acity": arrival_code,
            "direct": "true" if direct else "false",
            "army": "true" if army else "false"
        }

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"获取携程机票价格失败: {e}")
            return {
                "error": "请求携程机票API失败，未获取到实时价格",
                "details": str(e)
            }

        flight_info = {
            "departure_city": dcity,
            "arrival_city": acity,
            "departure_code": departure_code,
            "arrival_code": arrival_code,
            "flight_way": flight_way,
            "direct": direct,
            "army": army,
            "source": "ctrip_api_fallback"
        }

        def _flatten_price_list(price_list):
            flattened = {}
            for price_map in price_list:
                if isinstance(price_map, dict):
                    for key, value in price_map.items():
                        if isinstance(key, str) and isinstance(value, (int, float)):
                            flattened[key] = value
            return flattened

        if isinstance(data, dict):
            data_body = data.get("data") or data.get("result") or data
            if isinstance(data_body, dict):
                lowest_price = data_body.get("lowestPrice") or data_body.get("price") or data_body.get("minPrice")
                if lowest_price is not None:
                    flight_info["lowest_price"] = lowest_price
                    flight_info["currency"] = "CNY"
                    flight_info["raw_response"] = data
                    return flight_info

                if "oneWayPrice" in data_body and isinstance(data_body["oneWayPrice"], list):
                    price_map = _flatten_price_list(data_body["oneWayPrice"])
                    flight_info["prices_by_date"] = price_map
                    if requested_date:
                        if requested_date in price_map:
                            flight_info["requested_date"] = travel_date
                            flight_info["requested_price"] = price_map[requested_date]
                        else:
                            flight_info["requested_date"] = travel_date
                            flight_info["requested_price"] = None
                            flight_info["available_dates"] = sorted(price_map.keys())
                            flight_info["note"] = f"未找到 {travel_date} 的机票价格，已返回可用日期中的最低价"
                    flight_info["lowest_price"] = min(price_map.values()) if price_map else None
                    flight_info["currency"] = "CNY"
                    flight_info["raw_response"] = data
                    return flight_info

                if "roundTripPrice" in data_body and isinstance(data_body["roundTripPrice"], list):
                    price_map = _flatten_price_list(data_body["roundTripPrice"])
                    flight_info["prices_by_date"] = price_map
                    if requested_date:
                        if requested_date in price_map:
                            flight_info["requested_date"] = travel_date
                            flight_info["requested_price"] = price_map[requested_date]
                        else:
                            flight_info["requested_date"] = travel_date
                            flight_info["requested_price"] = None
                            flight_info["available_dates"] = sorted(price_map.keys())
                            flight_info["note"] = f"未找到 {travel_date} 的机票价格，已返回可用日期中的最低价"
                    flight_info["lowest_price"] = min(price_map.values()) if price_map else None
                    flight_info["currency"] = "CNY"
                    flight_info["raw_response"] = data
                    return flight_info

                if "route" in data_body and isinstance(data_body["route"], list) and data_body["route"]:
                    first_trip = data_body["route"][0]
                    flight_info["lowest_price"] = first_trip.get("price") or first_trip.get("lowestPrice")
                    flight_info["currency"] = "CNY"
                    flight_info["raw_response"] = data
                    return flight_info

        return {
            "error": "未能从携程API解析出最低价格",
            "source_data": data
        }

    def _scrape_ctrip_flight_price(self, dcity: str, acity: str,
                                   departure_code: str, arrival_code: str,
                                   flight_way: str, direct: bool, army: bool,
                                   travel_date: str, requested_date: str) -> Optional[Dict]:
        route_part = "oneway" if flight_way.lower() == "oneway" else "roundway"
        urls = [
            (
                f"https://flights.ctrip.com/online/list/{route_part}-{departure_code}-{arrival_code}"
                f"?date={travel_date}&directFlight={1 if direct else 0}"
            ),
            (
                f"https://flights.ctrip.com/online/channel/domestic/getAirline"
                f"?dcity={departure_code}&acity={arrival_code}&date={travel_date}"
            )
        ]

        if self.use_playwright_scraper:
            for url in urls:
                html = _fetch_page_html_with_playwright(
                    url,
                    headless=self.playwright_headless,
                    wait_selectors=["body"],
                    wait_ms=5000
                )
                if html:
                    parsed = self._extract_flight_price_from_text(
                        html,
                        dcity=dcity,
                        acity=acity,
                        departure_code=departure_code,
                        arrival_code=arrival_code,
                        flight_way=flight_way,
                        direct=direct,
                        army=army,
                        travel_date=travel_date,
                        requested_date=requested_date,
                        source_url=url
                    )
                    if parsed:
                        parsed["source"] = "flight_playwright_scraper"
                        return parsed

        for url in urls:
            try:
                response = self.session.get(url, timeout=20)
                response.raise_for_status()
                parsed = self._extract_flight_price_from_text(
                    response.text,
                    dcity=dcity,
                    acity=acity,
                    departure_code=departure_code,
                    arrival_code=arrival_code,
                    flight_way=flight_way,
                    direct=direct,
                    army=army,
                    travel_date=travel_date,
                    requested_date=requested_date,
                    source_url=url
                )
                if parsed:
                    return parsed
            except Exception as e:
                print(f"抓取携程机票页面失败: {e}")

        return None

    def _extract_flight_price_from_text(self, text: str, dcity: str, acity: str,
                                        departure_code: str, arrival_code: str,
                                        flight_way: str, direct: bool, army: bool,
                                        travel_date: str, requested_date: str,
                                        source_url: str) -> Optional[Dict]:
        date_price_map = {}

        for match in re.finditer(
            r'"(?P<date>20\d{6}|20\d{2}-\d{2}-\d{2})"\s*:\s*(?P<price>\d+(?:\.\d+)?)',
            text
        ):
            key = match.group("date").replace("-", "")
            date_price_map[key] = _normalize_price(match.group("price"))

        for match in re.finditer(
            r'"date"\s*:\s*"(?P<date>20\d{2}-\d{2}-\d{2}|20\d{6})".{0,120}?'
            r'"(?:price|lowestPrice|minPrice)"\s*:\s*"?(?P<price>\d+(?:\.\d+)?)"?',
            text,
            re.S
        ):
            key = match.group("date").replace("-", "")
            date_price_map[key] = _normalize_price(match.group("price"))

        lowest_candidates = [
            _normalize_price(value)
            for value in re.findall(r'"(?:lowestPrice|minPrice|price)"\s*:\s*"?(?:¥|￥)?(\d+(?:\.\d+)?)"?', text)
        ]
        lowest_candidates = [value for value in lowest_candidates if value is not None]

        if date_price_map:
            date_price_map = {
                key: int(value) if float(value).is_integer() else value
                for key, value in date_price_map.items()
                if value is not None
            }
            requested_price = date_price_map.get(requested_date)
            lowest_price = min(date_price_map.values()) if date_price_map else None
            result = {
                "departure_city": dcity,
                "arrival_city": acity,
                "departure_code": departure_code,
                "arrival_code": arrival_code,
                "flight_way": flight_way,
                "direct": direct,
                "army": army,
                "requested_date": travel_date,
                "requested_price": requested_price,
                "prices_by_date": date_price_map,
                "lowest_price": lowest_price,
                "currency": "CNY",
                "source": "flight_scraper",
                "source_url": source_url
            }
            if requested_price is None and requested_date:
                result["available_dates"] = sorted(date_price_map.keys())
                result["note"] = f"未找到 {travel_date} 的机票价格，已返回可用日期中的最低价"
            return result

        if lowest_candidates:
            lowest_price = min(lowest_candidates)
            return {
                "departure_city": dcity,
                "arrival_city": acity,
                "departure_code": departure_code,
                "arrival_code": arrival_code,
                "flight_way": flight_way,
                "direct": direct,
                "army": army,
                "requested_date": travel_date,
                "lowest_price": int(lowest_price) if float(lowest_price).is_integer() else lowest_price,
                "currency": "CNY",
                "source": "flight_scraper",
                "source_url": source_url
            }

        return None

    def _load_city_cost_reference(self) -> Dict:
        try:
            _json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'city_cost_reference.json')
            with open(_json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return self._get_default_cost_data()

    def get_weather(self, city: str, travel_dates: List[str]) -> List[Dict]:
        city_codes = {
            "北京": "110000",
            "上海": "310000",
            "广州": "440100",
            "深圳": "440300",
            "成都": "510100",
            "杭州": "330100",
            "西安": "610100",
            "重庆": "500000",
            "南京": "320100",
            "武汉": "420100"
        }
        if city not in city_codes:
            return self._get_mock_weather_list(city, travel_dates)

        api_key = os.getenv('AMAP_WEB_SERVICE_KEY')
        if not api_key:
            print("未配置 AMAP_WEB_SERVICE_KEY")
            if self.allow_mock_data:
                return self._get_mock_weather_list(city, travel_dates)
            return []

        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            "key": api_key,
            "city": city_codes[city],
            "extensions": "all"
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"获取天气数据失败: {e}")
            if self.allow_mock_data:
                return self._get_mock_weather_list(city, travel_dates)
            return []

        if data.get("status") != "1" or not data.get("forecasts"):
            print(f"高德地图API错误: {data.get('info')}")
            if self.allow_mock_data:
                return self._get_mock_weather_list(city, travel_dates)
            return []

        forecast_data = data["forecasts"][0]["casts"]
        available_dates = {day["date"]: day for day in forecast_data}
        result = []
        for requested_date in travel_dates:
            if requested_date in available_dates:
                day = available_dates[requested_date]
                advice = self._generate_weather_advice_amap(day)
                result.append({
                    "date": requested_date,
                    "temp": f"{day['nighttemp']}°C~{day['daytemp']}°C",
                    "condition": day["dayweather"],
                    "advice": advice,
                    "temp_max": f"{day['daytemp']}°C",
                    "temp_min": f"{day['nighttemp']}°C",
                    "humidity": "N/A",
                    "precip": "N/A",
                    "uv_index": "N/A",
                    "wind_speed": f"{day['daypower']}级",
                    "wind_direction": day["daywind"],
                    "visibility": "N/A",
                    "sunrise": "N/A",
                    "sunset": "N/A",
                    "source": "amap_api"
                })
            else:
                print(f"日期 {requested_date} 超出API预报范围，使用模拟数据")
                result.append(self._get_mock_weather_for_date(city, requested_date))
        return result

    def estimate_cost(self, city: str, days: int, budget_level: str,
                      user_budget: Optional[float] = None) -> Dict:
        if user_budget is not None and budget_level == "auto":
            budget_level = self._match_budget_level(city, days, user_budget)
        if city not in self.city_cost_data:
            city = "成都"
        if budget_level not in self.city_cost_data[city]:
            budget_level = "medium"
        cost_data = self.city_cost_data[city][budget_level]
        hotel_per_night = f"{cost_data['hotel_per_night']['min']}-{cost_data['hotel_per_night']['max']}元"
        food_per_day = f"{cost_data['food_per_day']['min']}-{cost_data['food_per_day']['max']}元"
        transport_days = min(days, 3)
        transport_min = cost_data["local_transport_total_per_3_days"]["min"] * (transport_days / 3)
        transport_max = cost_data["local_transport_total_per_3_days"]["max"] * (transport_days / 3)
        transport_total = f"{round(transport_min, 0)}-{round(transport_max, 0)}元"
        hotel_total_min = cost_data["hotel_per_night"]["min"] * days
        hotel_total_max = cost_data["hotel_per_night"]["max"] * days
        food_total_min = cost_data["food_per_day"]["min"] * days
        food_total_max = cost_data["food_per_day"]["max"] * days
        total_min = hotel_total_min + food_total_min + transport_min
        total_max = hotel_total_max + food_total_max + transport_max
        return {
            "酒店每晚": hotel_per_night,
            "餐饮每天": food_per_day,
            "交通合计": transport_total,
            "总计最低": round(total_min),
            "总计最高": round(total_max)
        }

    def _match_budget_level(self, city: str, days: int, user_budget: float) -> str:
        if city not in self.city_cost_data:
            city = "成都"
        level_costs = {}
        for level in ["low", "medium", "high"]:
            if level in self.city_cost_data[city]:
                cost_data = self.city_cost_data[city][level]
                hotel_min = cost_data["hotel_per_night"]["min"] * days
                food_min = cost_data["food_per_day"]["min"] * days
                transport_min = cost_data["local_transport_total_per_3_days"]["min"] * min(days, 3) / 3
                level_costs[level] = hotel_min + food_min + transport_min
        closest_level = "medium"
        min_diff = float('inf')
        for level, cost in level_costs.items():
            diff = abs(cost - user_budget)
            if diff < min_diff:
                min_diff = diff
                closest_level = level
        return closest_level

    def estimate_trip_budget(self, departure_city: str, destination_city: str,
                             depart_date: str, return_date: str,
                             budget_level: str = "medium",
                             adults: int = 1,
                             hotels: Optional[List[Dict]] = None,
                             outbound_flight: Optional[Dict] = None,
                             return_flight: Optional[Dict] = None,
                             user_budget: Optional[float] = None) -> Dict:
        travel_dates = _build_date_range(depart_date, return_date)
        travel_days = len(travel_dates)
        hotel_nights = max((datetime.strptime(return_date, "%Y-%m-%d") - datetime.strptime(depart_date, "%Y-%m-%d")).days, 1)

        city_for_cost = destination_city if destination_city in self.city_cost_data else "成都"
        if user_budget is not None and budget_level == "auto":
            budget_level = self._match_budget_level(city_for_cost, travel_days, user_budget)
        if budget_level not in self.city_cost_data.get(city_for_cost, {}):
            budget_level = "medium"

        cost_data = self.city_cost_data[city_for_cost][budget_level]
        notes = []

        hotel_prices = [
            _normalize_price(hotel.get("min_price"))
            for hotel in (hotels or [])
            if hotel.get("source") != "mock_data"
        ]
        hotel_prices = [price for price in hotel_prices if price is not None]
        hotel_price_source = "ctrip_hotel_scraper" if hotel_prices else "local_cost_reference"
        hotel_price_per_night = min(hotel_prices) if hotel_prices else (
            cost_data["hotel_per_night"]["min"] + cost_data["hotel_per_night"]["max"]
        ) / 2
        if not hotel_prices:
            notes.append("未抓到携程酒店实时价格，酒店预算改用本地城市住宿参考价")

        def _flight_price(info: Optional[Dict]) -> Optional[float]:
            if not info or info.get("error"):
                return None
            for key in ("requested_price", "lowest_price"):
                price = _normalize_price(info.get(key))
                if price is not None:
                    return price
            return None

        outbound_price = _flight_price(outbound_flight)
        inbound_price = _flight_price(return_flight)
        outbound_price_source = "realtime" if outbound_price is not None else "missing"
        inbound_price_source = "realtime" if inbound_price is not None else "missing"

        if outbound_price is None and inbound_price is not None:
            outbound_price = inbound_price
            outbound_price_source = "mirrored_from_return"
            notes.append("未抓到去程机票实时价格，预算按返程价格对称估算")
        elif inbound_price is None and outbound_price is not None:
            inbound_price = outbound_price
            inbound_price_source = "mirrored_from_outbound"
            notes.append("未抓到返程机票实时价格，预算按去程价格对称估算")
        elif inbound_price is None and outbound_price is None:
            notes.append("未抓到往返机票实时价格，机票预算暂按 0 元展示")

        flight_total = ((outbound_price or 0) + (inbound_price or 0)) * max(adults, 1)

        food_per_day_mid = (cost_data["food_per_day"]["min"] + cost_data["food_per_day"]["max"]) / 2
        food_total = food_per_day_mid * travel_days * max(adults, 1)

        transport_days = min(travel_days, 3)
        transport_total = (
            (cost_data["local_transport_total_per_3_days"]["min"] + cost_data["local_transport_total_per_3_days"]["max"]) / 2
        ) * (transport_days / 3)

        hotel_total = hotel_price_per_night * hotel_nights
        total_budget = flight_total + hotel_total + food_total + transport_total

        return {
            "departure_city": departure_city,
            "destination_city": destination_city,
            "depart_date": depart_date,
            "return_date": return_date,
            "travel_days": travel_days,
            "hotel_nights": hotel_nights,
            "adults": adults,
            "budget_level": budget_level,
            "机票预算": round(flight_total),
            "酒店预算": round(hotel_total),
            "餐饮预算": round(food_total),
            "本地交通预算": round(transport_total),
            "总预算": round(total_budget),
            "预算明细": {
                "去程机票单价": round(outbound_price) if outbound_price is not None else None,
                "返程机票单价": round(inbound_price) if inbound_price is not None else None,
                "酒店每晚参考价": round(hotel_price_per_night),
                "餐饮每天参考价": round(food_per_day_mid),
                "本地交通参考总价": round(transport_total)
            },
            "数据来源": {
                "outbound_flight_source": outbound_flight.get("source") if outbound_flight else None,
                "return_flight_source": return_flight.get("source") if return_flight else None,
                "hotel_source": hotels[0].get("source") if hotels else None,
                "hotel_budget_source": hotel_price_source,
                "outbound_budget_source": outbound_price_source,
                "return_budget_source": inbound_price_source,
                "cost_reference_city": city_for_cost
            },
            "说明": notes
        }

    def build_trip_plan(self, departure_city: str, destination_city: str,
                        depart_date: str, return_date: str,
                        budget_level: str = "medium",
                        user_budget: Optional[float] = None,
                        adults: int = 1,
                        direct: bool = True,
                        keyword: Optional[str] = None,
                        star_rate: Optional[int] = None) -> Dict:
        travel_dates = _build_date_range(depart_date, return_date)
        weather_info = self.get_weather(destination_city, travel_dates)
        hotels = self.search_hotels(destination_city, depart_date, return_date, keyword, star_rate)
        outbound_flight = self.get_flight_price(
            departure_city, destination_city, "Oneway", direct, False, depart_date
        )
        return_flight = self.get_flight_price(
            destination_city, departure_city, "Oneway", direct, False, return_date
        )
        budget_info = self.estimate_trip_budget(
            departure_city=departure_city,
            destination_city=destination_city,
            depart_date=depart_date,
            return_date=return_date,
            budget_level=budget_level,
            adults=adults,
            hotels=hotels,
            outbound_flight=outbound_flight,
            return_flight=return_flight,
            user_budget=user_budget
        )

        return {
            "departure_city": departure_city,
            "destination_city": destination_city,
            "depart_date": depart_date,
            "return_date": return_date,
            "travel_dates": travel_dates,
            "weather": weather_info,
            "hotels": hotels,
            "flights": {
                "outbound": outbound_flight,
                "return": return_flight
            },
            "budget": budget_info,
            "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    def search_hotels(self, city: str, check_in_date: str, check_out_date: str,
                      keyword: Optional[str] = None, star_rate: Optional[int] = None) -> List[Dict]:
        return self.hotel_api.search_hotels(city, check_in_date, check_out_date, keyword, star_rate)

    def get_hotel_details(self, hotel_id: str, check_in_date: str, check_out_date: str) -> Dict:
        return self.hotel_api.get_hotel_details(hotel_id, check_in_date, check_out_date)

    def _get_mock_weather_list(self, city: str, travel_dates: List[str]) -> List[Dict]:
        return [self._get_mock_weather_for_date(city, date) for date in travel_dates]

    def _get_mock_weather_for_date(self, city: str, date: str) -> Dict:
        return {
            "date": date,
            "temp": "20°C~28°C",
            "condition": "多云",
            "advice": f"{city}地区天气适中，适合户外活动（模拟数据）",
            "temp_max": "28°C",
            "temp_min": "20°C",
            "humidity": "N/A",
            "precip": "N/A",
            "uv_index": "N/A",
            "wind_speed": "3级",
            "wind_direction": "东南风",
            "visibility": "N/A",
            "sunrise": "N/A",
            "sunset": "N/A",
            "source": "mock_data"
        }

    def _generate_weather_advice_amap(self, day: Dict) -> str:
        day_temp = int(day.get("daytemp", 25))
        night_temp = int(day.get("nighttemp", 15))
        condition = day.get("dayweather", "晴")
        wind_power = day.get("daypower", "3")
        avg_temp = (day_temp + night_temp) / 2
        advice_parts = []
        if avg_temp < 10:
            advice_parts.append("天气寒冷，建议穿厚外套、保暖内衣")
        elif avg_temp < 15:
            advice_parts.append("天气较冷，建议穿外套和长袖")
        elif avg_temp < 20:
            advice_parts.append("天气凉爽，建议穿薄外套")
        elif avg_temp < 25:
            advice_parts.append("天气舒适，适合穿长袖")
        elif avg_temp < 30:
            advice_parts.append("天气温暖，适合穿短袖")
        else:
            advice_parts.append("天气炎热，建议多喝水，注意防晒")
        if "雨" in condition or "雪" in condition or "雷" in condition:
            advice_parts.append("有降水，建议带伞，安排室内活动")
        elif "雾" in condition or "霾" in condition:
            advice_parts.append("空气质量较差，出行注意防护")
        elif "沙" in condition or "尘" in condition:
            advice_parts.append("风沙天气，注意防风沙")
        try:
            wind_level = int(wind_power)
            if wind_level >= 6:
                advice_parts.append("风力较大，注意防风保暖")
        except (ValueError, TypeError):
            pass
        if not advice_parts:
            advice_parts.append("天气适中，适合户外活动")
        return "；".join(advice_parts)

    def _get_default_cost_data(self) -> Dict:
        return {
            "成都": {
                "low": {
                    "hotel_per_night": {"min": 100, "max": 180},
                    "food_per_day": {"min": 60, "max": 100},
                    "local_transport_total_per_3_days": {"min": 40, "max": 80}
                },
                "medium": {
                    "hotel_per_night": {"min": 250, "max": 400},
                    "food_per_day": {"min": 120, "max": 220},
                    "local_transport_total_per_3_days": {"min": 60, "max": 120}
                },
                "high": {
                    "hotel_per_night": {"min": 500, "max": 800},
                    "food_per_day": {"min": 300, "max": 500},
                    "local_transport_total_per_3_days": {"min": 150, "max": 300}
                }
            },
            "北京": {
                "low": {
                    "hotel_per_night": {"min": 120, "max": 200},
                    "food_per_day": {"min": 80, "max": 120},
                    "local_transport_total_per_3_days": {"min": 50, "max": 100}
                },
                "medium": {
                    "hotel_per_night": {"min": 300, "max": 500},
                    "food_per_day": {"min": 150, "max": 250},
                    "local_transport_total_per_3_days": {"min": 80, "max": 150}
                },
                "high": {
                    "hotel_per_night": {"min": 600, "max": 1000},
                    "food_per_day": {"min": 400, "max": 600},
                    "local_transport_total_per_3_days": {"min": 200, "max": 400}
                }
            },
            "上海": {
                "low": {
                    "hotel_per_night": {"min": 150, "max": 250},
                    "food_per_day": {"min": 100, "max": 150},
                    "local_transport_total_per_3_days": {"min": 60, "max": 120}
                },
                "medium": {
                    "hotel_per_night": {"min": 350, "max": 550},
                    "food_per_day": {"min": 180, "max": 280},
                    "local_transport_total_per_3_days": {"min": 100, "max": 180}
                },
                "high": {
                    "hotel_per_night": {"min": 700, "max": 1200},
                    "food_per_day": {"min": 450, "max": 700},
                    "local_transport_total_per_3_days": {"min": 250, "max": 450}
                }
            }
        }


weather_api = WeatherCostAPI()


def get_weather_api(city: str, travel_dates: List[str]) -> List[Dict]:
    return weather_api.get_weather(city, travel_dates)


def estimate_cost_api(city: str, days: int, budget_level: str,
                      user_budget: Optional[float] = None) -> Dict:
    return weather_api.estimate_cost(city, days, budget_level, user_budget)


def search_hotels_api(city: str, check_in_date: str, check_out_date: str,
                      keyword: Optional[str] = None, star_rate: Optional[int] = None) -> List[Dict]:
    return weather_api.search_hotels(city, check_in_date, check_out_date, keyword, star_rate)


def get_hotel_details_api(hotel_id: str, check_in_date: str, check_out_date: str) -> Dict:
    return weather_api.get_hotel_details(hotel_id, check_in_date, check_out_date)


def prepare_ctrip_hotel_login_api() -> bool:
    return weather_api.hotel_api.prepare_ctrip_login_session()


def get_flight_price_api(dcity: str, acity: str, flight_way: str = "Oneway",
                         direct: bool = True, army: bool = False,
                         travel_date: Optional[str] = None) -> Dict:
    return weather_api.get_flight_price(dcity, acity, flight_way, direct, army, travel_date)


def get_provider_status_api() -> Dict:
    return weather_api.get_provider_status()


def get_trip_plan_api(departure_city: str, destination_city: str,
                      depart_date: str, return_date: str,
                      budget_level: str = "medium",
                      user_budget: Optional[float] = None,
                      adults: int = 1,
                      direct: bool = True,
                      keyword: Optional[str] = None,
                      star_rate: Optional[int] = None) -> Dict:
    return weather_api.build_trip_plan(
        departure_city=departure_city,
        destination_city=destination_city,
        depart_date=depart_date,
        return_date=return_date,
        budget_level=budget_level,
        user_budget=user_budget,
        adults=adults,
        direct=direct,
        keyword=keyword,
        star_rate=star_rate
    )


def get_travel_info(city: str, travel_dates: List[str], days: int,
                    budget_level: str = "medium", user_budget: Optional[float] = None,
                    dcity: Optional[str] = None, acity: Optional[str] = None,
                    flight_way: str = "Oneway", direct: bool = True,
                    army: bool = False, travel_date: Optional[str] = None) -> Dict:
    if dcity and acity and travel_dates:
        depart_date = travel_dates[0]
        return_date = travel_dates[-1]
        return get_trip_plan_api(
            departure_city=dcity,
            destination_city=acity,
            depart_date=depart_date,
            return_date=return_date,
            budget_level=budget_level,
            user_budget=user_budget,
            adults=1,
            direct=direct
        )

    weather_info = weather_api.get_weather(city, travel_dates)
    cost_info = weather_api.estimate_cost(city, days, budget_level, user_budget)
    check_in_date = travel_dates[0] if travel_dates else datetime.now().strftime('%Y-%m-%d')
    check_out_date = (datetime.strptime(check_in_date, '%Y-%m-%d') + timedelta(days=days)).strftime('%Y-%m-%d')
    hotels = weather_api.search_hotels(city, check_in_date, check_out_date)

    return {
        "weather": weather_info,
        "cost": cost_info,
        "hotels": hotels,
        "city": city,
        "travel_dates": travel_dates,
        "days": days,
        "budget_level": budget_level,
        "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


def _run_demo_tests() -> None:
    print("=== C组统一旅行信息API测试 ===\n")
    print("0. 运行状态检查:")
    print(json.dumps(get_provider_status_api(), ensure_ascii=False, indent=2))

    print("1. 天气API测试:")
    weather_result = get_weather_api("杭州", ["2026-04-23", "2026-04-28"])
    print(f"获取到 {len(weather_result)} 天天气数据")
    if weather_result:
        print(f"第一天: {weather_result[0]['condition']} {weather_result[0]['temp']}")

    print("\n2. 费用API测试:")
    cost_result = estimate_cost_api("杭州", 3, "medium", 2000)
    print(f"杭州3天中等预算: {cost_result['总计最低']}-{cost_result['总计最高']}元")

    print("\n3. 酒店API测试:")
    hotels = search_hotels_api("杭州", "2026-04-23", "2026-04-28")
    print(f"找到 {len(hotels)} 家酒店")
    if hotels:
        print(f"示例酒店: {hotels[0]['name']}")

    print("\n4. 机票API测试:")
    flight_result = get_flight_price_api("南宁", "杭州", "Oneway", True, False)
    print(f"机票查询结果: {flight_result.get('requested_price') or flight_result.get('lowest_price') or flight_result.get('error')}")

    print("\n4.1. 指定日期机票API测试:")
    flight_result_by_date = get_flight_price_api("南宁", "武汉", "Oneway", True, False, "2026-04-21")
    print(f"指定日期机票结果: {flight_result_by_date.get('requested_price') or flight_result_by_date.get('lowest_price') or flight_result_by_date.get('error')}")

    print("\n5. 统一旅行信息API测试:")
    travel_info = get_travel_info("杭州", ["2026-04-23", "2026-04-28"], 3, "medium")
    print("✅ 统一API返回完整旅行信息:")
    print(f"  - 天气数据: {len(travel_info['weather'])} 天")
    print(f"  - 费用估算: {travel_info['cost']['总计最低']}-{travel_info['cost']['总计最高']}元")
    print(f"  - 酒店推荐: {len(travel_info['hotels'])} 家")

    print("\n6. 用户输入式行程预算测试:")
    trip_plan = get_trip_plan_api("南宁", "杭州", "2026-04-23", "2026-04-28", "medium")
    print("✅ 行程规划结果:")
    print(f"  - 查询天气: {len(trip_plan['weather'])} 天")
    print(f"  - 去程机票: {trip_plan['flights']['outbound'].get('requested_price') or trip_plan['flights']['outbound'].get('lowest_price') or trip_plan['flights']['outbound'].get('error')}")
    print(f"  - 返程机票: {trip_plan['flights']['return'].get('requested_price') or trip_plan['flights']['return'].get('lowest_price') or trip_plan['flights']['return'].get('error')}")
    print(f"  - 总预算: {trip_plan['budget']['总预算']}元")
    print("\n🎉 C组API整合完成！")


def _run_interactive_trip_planner() -> None:
    print("=== C组旅行预算查询 ===")
    print("请输入出发地、目的地、去程日期、返程日期，程序会返回天气、机票、酒店和预算。\n")

    departure_city = input("出发地: ").strip()
    destination_city = input("目的地: ").strip()
    depart_date = input("去程日期 (YYYY-MM-DD): ").strip()
    return_date = input("返程日期 (YYYY-MM-DD): ").strip()
    budget_level = input("预算等级 (low/medium/high，默认 medium): ").strip() or "medium"

    try:
        result = get_trip_plan_api(
            departure_city=departure_city,
            destination_city=destination_city,
            depart_date=depart_date,
            return_date=return_date,
            budget_level=budget_level
        )
    except Exception as exc:
        print(f"\n查询失败: {exc}")
        return

    print("\n=== 查询结果 ===")
    print(f"行程: {departure_city} -> {destination_city}")
    print(f"日期: {depart_date} 到 {return_date}")
    print(f"天气天数: {len(result['weather'])}")
    if result["weather"]:
        first_day = result["weather"][0]
        print(f"首日天气: {first_day['condition']} {first_day['temp']}")

    outbound = result["flights"]["outbound"]
    inbound = result["flights"]["return"]
    print(f"去程机票参考: {outbound.get('requested_price') or outbound.get('lowest_price') or outbound.get('error')}")
    print(f"返程机票参考: {inbound.get('requested_price') or inbound.get('lowest_price') or inbound.get('error')}")

    hotels = result["hotels"]
    if hotels:
        first_hotel = hotels[0]
        if first_hotel.get("min_price") is not None:
            print(f"酒店参考: {first_hotel['name']} / {first_hotel.get('min_price')}元起")
        else:
            print(f"酒店参考: {first_hotel['name']} / 公开页未显示价格")
            if first_hotel.get("price_note"):
                print(f"酒店价格说明: {first_hotel['price_note']}")
    else:
        print("酒店参考: 未抓到携程实时酒店价格，已改用本地住宿参考价估算")

    print(f"总预算: {result['budget']['总预算']}元")
    print(f"预算拆分: 机票{result['budget']['机票预算']}元, 酒店{result['budget']['酒店预算']}元, 餐饮{result['budget']['餐饮预算']}元, 本地交通{result['budget']['本地交通预算']}元")
    if result["budget"].get("说明"):
        print("说明:")
        for note in result["budget"]["说明"]:
            print(f"  - {note}")


if __name__ == "__main__":
    if _env_flag("RUN_DEMO_TESTS", False):
        _run_demo_tests()
    else:
        _run_interactive_trip_planner()
