# Group C Travel Information API

This project is a Python-based travel information aggregator for:

- Weather lookup
- Hotel search
- Flight price lookup
- Budget estimation
- End-to-end trip planning

The main file is [c_group_weather_cost_api.py](./c_group_weather_cost_api.py).

## Current Status

The project currently supports:

- Weather data from AMap
- Flight price scraping / fallback API logic for Ctrip
- Hotel list scraping from Ctrip
- Logged-in Playwright hotel price scraping from Ctrip
- Local fallback cost estimation when real-time price data is unavailable

Important limitation:

- Ctrip hotel prices are generally not visible on the public page without login.
- To get hotel prices reliably, you should log in to your own Ctrip account once through the Playwright persistent browser session.

## Project Structure

- [c_group_weather_cost_api.py](./c_group_weather_cost_api.py): main implementation
- [.env.example](./.env.example): example environment configuration
- [.gitignore](./.gitignore): ignored local files

All commands in this README assume your terminal is already inside the project folder that contains `c_group_weather_cost_api.py`.

## Environment Setup

Recommended environment:

- Windows
- Conda
- Python 3.11

Create and use the environment:

```powershell
conda create -y -n groupc-playwright python=3.11 pip
conda activate groupc-playwright
cd path\to\Group_C
python -m pip install requests playwright
python -m playwright install chromium
```

Replace `path\to\Group_C` with the local path to this project on your own machine.

## Configuration

Create a local `.env` file based on [.env.example](./.env.example).

Recommended local config for hotel price testing:

```env
AMAP_WEB_SERVICE_KEY=your_amap_key
USE_PLAYWRIGHT_SCRAPER=true
PLAYWRIGHT_HEADLESS=false
USE_PERSISTENT_LOGIN_CONTEXT=true
CTRIP_MANUAL_LOGIN_ON_START=false
PLAYWRIGHT_USER_DATA_DIR=.playwright/ctrip-user-data
CTRIP_HOTEL_ENTRY_URL=https://hotels.ctrip.com/?allianceid=4899&sid=963772
ALLOW_MOCK_DATA=true
```

Notes:

- `PLAYWRIGHT_HEADLESS=false` is required for first-time manual login.
- `.playwright/` is ignored by git so local login state will not be committed.

## First-Time Ctrip Login

Run the following once:

```powershell
conda activate groupc-playwright
cd path\to\Group_C
python -c "from c_group_weather_cost_api import prepare_ctrip_hotel_login_api; print(prepare_ctrip_hotel_login_api())"
```

What happens:

1. A Chromium browser window opens.
2. Log in to your own Ctrip account manually.
3. Return to the terminal and press Enter.
4. The login session is saved under `.playwright/ctrip-user-data`.

After that, later hotel scraping runs can reuse the saved login state.

## Run Hotel Test

```powershell
conda activate groupc-playwright
cd path\to\Group_C
python -c "from c_group_weather_cost_api import search_hotels_api; import json; hotels = search_hotels_api('上海','2026-05-01','2026-05-03'); print('count=', len(hotels)); print('sources=', sorted(set(h.get('source') for h in hotels if h.get('source')))); print(json.dumps(hotels[:3], ensure_ascii=False, indent=2))"
```

Expected success signals:

- `sources=['hotel_playwright_scraper']`
- `min_price` contains real numeric values

If scraping falls back to public-page parsing, you may instead see:

- `sources=['hotel_init_data']`
- `price_note` such as `登录以查看会员价`
- `min_price` as `null`

## Run Interactive Mode

```powershell
conda activate groupc-playwright
cd path\to\Group_C
python c_group_weather_cost_api.py
```

The script will prompt for:

- departure city
- destination city
- depart date
- return date
- budget level

Then it returns:

- weather
- hotel recommendations
- flight references
- total estimated budget

## Available Top-Level APIs

The main file exposes these helper functions:

- `get_weather_api(city, travel_dates)`
- `estimate_cost_api(city, days, budget_level, user_budget=None)`
- `search_hotels_api(city, check_in_date, check_out_date, keyword=None, star_rate=None)`
- `get_hotel_details_api(hotel_id, check_in_date, check_out_date)`
- `prepare_ctrip_hotel_login_api()`
- `get_flight_price_api(dcity, acity, flight_way="Oneway", direct=True, army=False, travel_date=None)`
- `get_provider_status_api()`
- `get_trip_plan_api(...)`
- `get_travel_info(...)`

## Improvements Made

Compared with the original version, the current code includes:

- Playwright anti-detection adjustments
- Better hotel result parsing
- Support for `__NEXT_DATA__` fallback parsing
- Windows-compatible input handling
- Persistent browser login session for Ctrip
- Hotel price extraction cleanup to avoid obvious invalid values such as `1.0`
- Budget fallback logic when live hotel prices are unavailable

## Known Limitations

- Hotel prices are dependent on Ctrip login state.
- Logged-in prices may vary by account, date, and platform rules.
- Some Playwright UI actions on the Ctrip entry page may still fail, but the code can directly visit the hotel result page afterward.
- The hotel detail / room rate / availability APIs are still placeholder implementations.
- This project is best treated as a course-project prototype rather than a production-grade travel data service.

## Safety Notes

- Do not hardcode your Ctrip password into the code.
- Do not commit `.env` or `.playwright/` to the repository.
- Use your own account only for local testing.

## Quick Summary

If you only want the shortest path to hotel price scraping:

1. Create and activate `groupc-playwright`
2. Install `requests` and `playwright`
3. Run `prepare_ctrip_hotel_login_api()`
4. Log in manually once
5. Run `search_hotels_api(...)`
