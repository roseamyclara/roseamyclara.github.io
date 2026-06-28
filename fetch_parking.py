import requests
from bs4 import BeautifulSoup
import json
import time
import os

API_KEY = os.environ["GOOGLE_MAPS_API_KEY"]  # 從 GitHub Secrets 讀取

def fetch_parking_list():
    url = "https://tcparking.taichung.gov.tw/ParkWeb/Pages/PublicService/LoveCardSchedule"
    # 直接請求，不需 CORS proxy（Python 伺服器端沒有跨域限制）
    response = requests.get(url, timeout=15)
    response.encoding = "utf-8"
    
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("#PrintArea table tbody tr")
    
    parking_list = []
    for i, row in enumerate(rows):
        cells = row.select("td")
        if len(cells) >= 4 and i > 0:
            parking_list.append({
                "id":      cells[0].get_text(strip=True),
                "name":    cells[1].get_text(strip=True),
                "method":  cells[2].get_text(strip=True),
                "address": cells[3].get_text(strip=True),
                "lat": None,
                "lng": None
            })
    return parking_list

def geocode_address(address):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address + ", 臺中市", "key": API_KEY, "language": "zh-TW"}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    if data["status"] == "OK":
        loc = data["results"][0]["geometry"]["location"]
        return loc["lat"], loc["lng"]
    return None, None

def main():
    print("🔍 抓取停車場清單...")
    parking_list = fetch_parking_list()
    print(f"✅ 共 {len(parking_list)} 筆，開始 Geocoding...")
    
    success = 0
    for i, item in enumerate(parking_list):
        lat, lng = geocode_address(item["address"])
        item["lat"] = lat
        item["lng"] = lng
        if lat:
            success += 1
        # 每筆間隔 100ms，避免打爆 API 配額
        time.sleep(0.1)
        if (i + 1) % 10 == 0:
            print(f"  進度：{i+1}/{len(parking_list)}")
    
    # 只保留有座標的資料
    result = [p for p in parking_list if p["lat"] is not None]
    
    output_path = "data/parking.json"
    os.makedirs("data", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 完成！成功 {success}/{len(parking_list)} 筆，已寫入 {output_path}")

if __name__ == "__main__":
    main()
