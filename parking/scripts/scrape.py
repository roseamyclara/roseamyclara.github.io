#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爬取臺中市停車資訊網「身障免銷單服務已上線停車場」表格。

輸出：parking/cache/parkings_raw.json

設計原則：
  * 不依賴網站的 CSS class 或 id（政府網站改版頻繁），改用表頭文字比對欄位。
  * 有健全性檢查（筆數過少直接失敗），避免把壞資料 commit 進 repo。
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://tcparking.taichung.gov.tw/ParkWeb/Pages/PublicService/LoveCardSchedule"
ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "cache" / "parkings_raw.json"

TPE = timezone(timedelta(hours=8))

# 表頭關鍵字 -> 輸出欄位名稱
COLUMN_MAP = [
    (("序號", "編號", "項次"), "seq"),
    (("停車場名稱", "停車場", "場站名稱", "名稱"), "name"),
    (("免銷單進出場方式", "進出場方式", "進出方式", "方式"), "access"),
    (("位置", "地址", "地點"), "location"),
]

MIN_EXPECTED_ROWS = 50  # 健全性門檻：實際約 285 筆

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def fetch(url: str, retries: int = 4) -> str:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=45)
            resp.raise_for_status()
            # 政府網站偶爾沒宣告編碼，交給 apparent_encoding 判斷
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as err:  # noqa: BLE001
            last_err = err
            wait = attempt * 5
            print(f"[warn] 第 {attempt} 次抓取失敗：{err}；{wait} 秒後重試", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"抓取 {url} 連續 {retries} 次失敗：{last_err}")


def clean(text: str) -> str:
    """壓縮空白、全形空格，並統一「台/臺」為「臺」以利後續比對。"""
    text = text.replace("　", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def match_column(header_text: str) -> str | None:
    h = clean(header_text)
    for keywords, field in COLUMN_MAP:
        for kw in keywords:
            if kw in h:
                return field
    return None


def pick_table(soup: BeautifulSoup):
    """挑出資料表：優先找表頭含『停車場名稱』者，否則取列數最多的表。"""
    tables = soup.find_all("table")
    if not tables:
        raise RuntimeError("頁面上找不到任何 <table>，網站結構可能已改版")

    scored = []
    for tbl in tables:
        rows = tbl.find_all("tr")
        header_cells = rows[0].find_all(["th", "td"]) if rows else []
        header_txt = " ".join(clean(c.get_text()) for c in header_cells)
        has_name = "停車場" in header_txt or "名稱" in header_txt
        scored.append((has_name, len(rows), tbl))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]


def parse_header(table) -> tuple[dict[int, str], int]:
    """回傳 {欄位索引: 欄位名稱} 以及資料列的起始索引。"""
    rows = table.find_all("tr")
    for idx, row in enumerate(rows[:5]):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        mapping = {}
        for i, cell in enumerate(cells):
            field = match_column(cell.get_text())
            if field and field not in mapping.values():
                mapping[i] = field
        if "name" in mapping.values():
            return mapping, idx + 1
    # 找不到表頭時退回固定欄位順序（序號/名稱/方式/位置）
    print("[warn] 無法辨識表頭，改用預設欄位順序", file=sys.stderr)
    return {0: "seq", 1: "name", 2: "access", 3: "location"}, 0


DISTRICT_RE = re.compile(r"([一-鿿]{1,3}區)")


def extract_district(location: str, name: str) -> str:
    for text in (location, name):
        m = DISTRICT_RE.search(text or "")
        if m:
            return m.group(1)
    return "未分類"


def normalize_address(location: str) -> str:
    """組出可送進地理編碼的完整地址。"""
    loc = clean(location or "").replace("台", "臺")
    if not loc:
        return ""
    if loc.startswith("臺中市"):
        return loc
    return "臺中市" + loc


def parse_updated_date(page_text: str) -> str | None:
    """從『(115年8月17日更新)』抓出民國日期並轉成西元 ISO 日期。"""
    m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*更新", page_text)
    if not m:
        return None
    roc_year, month, day = (int(g) for g in m.groups())
    year = roc_year + 1911 if roc_year < 1911 else roc_year
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except Exception:  # noqa: BLE001
        return None


def scrape() -> dict:
    html = fetch(SOURCE_URL)
    soup = BeautifulSoup(html, "lxml")
    page_text = clean(soup.get_text(" "))

    table = pick_table(soup)
    col_map, start = parse_header(table)
    rows = table.find_all("tr")[start:]

    items = []
    seen = set()
    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        rec = {"seq": "", "name": "", "access": "", "location": ""}
        for i, cell in enumerate(cells):
            field = col_map.get(i)
            if field:
                rec[field] = clean(cell.get_text(" "))
        name = rec["name"].replace("台", "臺")
        if not name or name in ("停車場名稱", "名稱"):
            continue

        key = (name, rec["location"])
        if key in seen:
            continue
        seen.add(key)

        location = clean(rec["location"]).replace("台", "臺")
        items.append(
            {
                "seq": rec["seq"],
                "name": name,
                "access": rec["access"],
                "location": location,
                "district": extract_district(location, name),
                "address": normalize_address(location),
            }
        )

    if len(items) < MIN_EXPECTED_ROWS:
        raise RuntimeError(
            f"只解析到 {len(items)} 筆資料（預期至少 {MIN_EXPECTED_ROWS} 筆），"
            "疑似網站改版或被擋，中止以避免覆蓋既有資料"
        )

    title = clean(soup.title.get_text()) if soup.title else ""

    return {
        "source_url": SOURCE_URL,
        "source_title": title,
        "page_updated": parse_updated_date(page_text),
        "scraped_at": datetime.now(TPE).isoformat(timespec="seconds"),
        "count": len(items),
        "items": items,
    }


def main() -> int:
    data = scrape()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"[ok] 取得 {data['count']} 筆停車場資料"
        f"（網站更新日：{data['page_updated'] or '未知'}）→ {OUT_PATH.relative_to(ROOT)}"
    )
    districts = {}
    for it in data["items"]:
        districts[it["district"]] = districts.get(it["district"], 0) + 1
    top = sorted(districts.items(), key=lambda x: -x[1])[:8]
    print("[ok] 行政區分布：" + "、".join(f"{d} {n}" for d, n in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
