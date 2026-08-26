#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把爬到的停車場資料轉成含經緯度的前端資料檔。

流程：
  parking/cache/parkings_raw.json  ──┐
  parking/cache/geocache.json  ─────┼──► parking/data/parkings.json
                            │
        Google Places / Geocoding API（只查快取沒有的項目）

金鑰讀取環境變數 GOOGLE_MAPS_API_KEY。
若沒有金鑰，會改用 OpenStreetMap Nominatim（免費、精度略低），
仍可產出可用的網站資料。

用法：
    python parking/scripts/geocode.py                # 一般執行（用快取）
    python parking/scripts/geocode.py --refresh-all  # 忽略快取全部重查（會計費，慎用）
    python parking/scripts/geocode.py --provider osm # 強制使用 Nominatim
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "cache" / "parkings_raw.json"
CACHE_PATH = ROOT / "cache" / "geocache.json"
OUT_PATH = ROOT / "data" / "parkings.json"

TPE = timezone(timedelta(hours=8))

# 臺中市大致範圍，用來剔除明顯編碼錯誤的座標
TC_BOUNDS = {"lat_min": 23.90, "lat_max": 24.60, "lng_min": 120.35, "lng_max": 121.50}
TC_CENTER = (24.1477, 120.6736)

PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

NOMINATIM_UA = "taichung-lovecard-parking-map/1.0 (github pages static site)"

# Google Geocoding 回傳的精度等級，越前面越精確
PRECISION_RANK = {
    "ROOFTOP": 4,
    "RANGE_INTERPOLATED": 3,
    "GEOMETRIC_CENTER": 2,
    "APPROXIMATE": 1,
}


def in_taichung(lat: float, lng: float) -> bool:
    return (
        TC_BOUNDS["lat_min"] <= lat <= TC_BOUNDS["lat_max"]
        and TC_BOUNDS["lng_min"] <= lng <= TC_BOUNDS["lng_max"]
    )


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        print(f"[warn] 讀取 {path.name} 失敗（{err}），視為空白", file=sys.stderr)
        return default


def cache_key(item: dict) -> str:
    return f"{item['name']}|{item['location']}"


# --------------------------------------------------------------------------
# Google
# --------------------------------------------------------------------------

def google_places(query: str, api_key: str) -> dict | None:
    """用 Places Text Search 找實際的停車場 POI（比純地址精準）。"""
    params = {
        "query": query,
        "key": api_key,
        "language": "zh-TW",
        "region": "tw",
        "location": f"{TC_CENTER[0]},{TC_CENTER[1]}",
        "radius": 30000,
    }
    resp = requests.get(PLACES_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        raise RuntimeError(f"Places API 回傳 {status}：{data.get('error_message', '')}")

    for result in data.get("results", []):
        loc = result["geometry"]["location"]
        if in_taichung(loc["lat"], loc["lng"]):
            return {
                "lat": round(loc["lat"], 6),
                "lng": round(loc["lng"], 6),
                "precision": "PLACE",
                "matched": result.get("name", ""),
                "formatted": result.get("formatted_address", ""),
                "source": "google_places",
            }
    return None


def google_geocode(address: str, api_key: str) -> dict | None:
    params = {
        "address": address,
        "key": api_key,
        "language": "zh-TW",
        "region": "tw",
        "components": "country:TW|administrative_area:臺中市",
    }
    resp = requests.get(GEOCODE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        raise RuntimeError(f"Geocoding API 回傳 {status}：{data.get('error_message', '')}")

    best, best_rank = None, -1
    for result in data.get("results", []):
        loc = result["geometry"]["location"]
        if not in_taichung(loc["lat"], loc["lng"]):
            continue
        rank = PRECISION_RANK.get(result["geometry"].get("location_type", ""), 0)
        if rank > best_rank:
            best_rank = rank
            best = {
                "lat": round(loc["lat"], 6),
                "lng": round(loc["lng"], 6),
                "precision": result["geometry"].get("location_type", "UNKNOWN"),
                "matched": "",
                "formatted": result.get("formatted_address", ""),
                "source": "google_geocode",
            }
    return best


# --------------------------------------------------------------------------
# OpenStreetMap fallback
# --------------------------------------------------------------------------

def osm_geocode(query: str) -> dict | None:
    params = {
        "q": query,
        "format": "jsonv2",
        "countrycodes": "tw",
        "limit": 3,
        "accept-language": "zh-TW",
    }
    resp = requests.get(
        NOMINATIM_URL, params=params, headers={"User-Agent": NOMINATIM_UA}, timeout=30
    )
    resp.raise_for_status()
    for result in resp.json():
        lat, lng = float(result["lat"]), float(result["lon"])
        if in_taichung(lat, lng):
            return {
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "precision": "OSM_" + str(result.get("type", "")).upper(),
                "matched": result.get("name", ""),
                "formatted": result.get("display_name", ""),
                "source": "nominatim",
            }
    return None


# --------------------------------------------------------------------------

def resolve(item: dict, provider: str, api_key: str | None) -> dict | None:
    name = item["name"]
    address = item["address"] or ("臺中市 " + name)

    if provider == "google" and api_key:
        # 先用「地址 + 場站名稱」找 POI，找不到再退回純地址
        hit = google_places(f"{address} {name}", api_key)
        if not hit:
            hit = google_places(f"臺中市 {name}", api_key)
        if not hit:
            hit = google_geocode(address, api_key)
        return hit

    hit = osm_geocode(f"{address} {name}")
    if not hit:
        hit = osm_geocode(address)
    return hit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-all", action="store_true", help="忽略快取，全部重新編碼")
    parser.add_argument(
        "--provider", choices=["auto", "google", "osm"], default="auto",
        help="auto：有金鑰用 Google，沒有就用 OSM",
    )
    parser.add_argument("--limit", type=int, default=0, help="本次最多編碼幾筆（0 = 不限）")
    args = parser.parse_args()

    raw = load_json(RAW_PATH, None)
    if not raw or not raw.get("items"):
        print(f"[error] 找不到或無法讀取 {RAW_PATH}，請先執行 scrape.py", file=sys.stderr)
        return 1

    api_key = (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
    if args.provider == "google":
        provider = "google"
        if not api_key:
            print("[error] 指定 --provider google 但沒有 GOOGLE_MAPS_API_KEY", file=sys.stderr)
            return 1
    elif args.provider == "osm":
        provider = "osm"
    else:
        provider = "google" if api_key else "osm"

    print(f"[info] 地理編碼服務：{provider}")
    if provider == "osm":
        print("[info] 使用 Nominatim，依其使用規範每次查詢間隔 1 秒")

    cache: dict = load_json(CACHE_PATH, {})
    if args.refresh_all:
        print("[info] --refresh-all：清空快取重新編碼")
        cache = {}

    items = raw["items"]
    todo = [it for it in items if cache_key(it) not in cache]
    if args.limit and len(todo) > args.limit:
        print(f"[info] 本次僅處理 {args.limit} / {len(todo)} 筆待編碼項目")
        todo = todo[: args.limit]

    print(f"[info] 共 {len(items)} 筆，快取命中 {len(items) - len(todo)} 筆，需查詢 {len(todo)} 筆")

    ok = fail = 0
    for idx, item in enumerate(todo, 1):
        key = cache_key(item)
        try:
            hit = resolve(item, provider, api_key)
        except Exception as err:  # noqa: BLE001
            print(f"[error] {item['name']}：{err}", file=sys.stderr)
            # API 層級錯誤（金鑰無效、額度用盡）就停止，避免整批失敗
            if "REQUEST_DENIED" in str(err) or "OVER_QUERY_LIMIT" in str(err):
                print("[error] API 呼叫被拒或超額，提前結束本次編碼", file=sys.stderr)
                break
            hit = None

        if hit:
            cache[key] = {**hit, "cached_at": datetime.now(TPE).isoformat(timespec="seconds")}
            ok += 1
        else:
            fail += 1
            print(f"[warn] 查不到座標：{item['name']}（{item['location']}）", file=sys.stderr)

        if idx % 25 == 0:
            print(f"[info] 進度 {idx}/{len(todo)}")
            CACHE_PATH.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

        time.sleep(1.0 if provider == "osm" else 0.12)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 組出前端資料
    out_items = []
    missing = 0
    for item in items:
        geo = cache.get(cache_key(item))
        rec = {
            "id": cache_key(item),
            "seq": item["seq"],
            "name": item["name"],
            "access": item["access"],
            "location": item["location"],
            "district": item["district"],
            "address": item["address"],
        }
        if geo:
            rec["lat"] = geo["lat"]
            rec["lng"] = geo["lng"]
            rec["precision"] = geo.get("precision", "")
            rec["geo_source"] = geo.get("source", "")
        else:
            missing += 1
        out_items.append(rec)

    payload = {
        "generated_at": datetime.now(TPE).isoformat(timespec="seconds"),
        "source_url": raw["source_url"],
        "page_updated": raw.get("page_updated"),
        "scraped_at": raw.get("scraped_at"),
        "count": len(out_items),
        "geocoded": len(out_items) - missing,
        "districts": sorted({i["district"] for i in out_items}),
        "access_types": sorted({i["access"] for i in out_items if i["access"]}),
        "items": out_items,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[ok] 本次新編碼成功 {ok} 筆、失敗 {fail} 筆")
    print(f"[ok] 輸出 {payload['count']} 筆（含座標 {payload['geocoded']} 筆）→ {OUT_PATH.relative_to(ROOT)}")

    if payload["geocoded"] == 0:
        print("[error] 沒有任何一筆取得座標，視為失敗", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
