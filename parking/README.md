# 臺中市身障免銷單停車場地圖

網站：**https://roseamyclara.github.io/parking/**

把[臺中市停車資訊網「身障免銷單服務已上線停車場」](https://tcparking.taichung.gov.tw/ParkWeb/Pages/PublicService/LoveCardSchedule)
的表格每天自動爬下來、轉成經緯度，做成可以即時搜尋的地圖。

```
  臺中市停車資訊網
        │  ① scrape.py（每天 00:00 由 GitHub Actions 執行）
        ▼
  parking/cache/parkings_raw.json
        │  ② geocode.py（把地址轉座標，結果存快取，只查新增的）
        ▼
  parking/data/parkings.json ──► ③ parking/index.html（Leaflet 地圖）
```

## 檔案在哪

| 路徑 | 用途 |
| --- | --- |
| `.github/workflows/update-parking.yml` | 每日排程（**一定要放在 `.github/workflows/` 裡才會執行**） |
| `parking/index.html` | 網站本體 |
| `parking/lib/` | Leaflet 地圖函式庫（已內含，不靠外部 CDN） |
| `parking/scripts/` | 爬蟲與地理編碼程式 |
| `parking/cache/` | 中繼檔與座標快取（自動產生、自動 commit） |
| `parking/data/parkings.json` | 網站讀取的資料檔（自動產生） |

## 功能

- 🔍 關鍵字搜尋停車場名稱、路名、行政區
- 📍 地點搜尋：輸入「臺中車站」「中國醫藥大學」等任意地點，找出附近停車場並依距離排序
- 🧭 「離我最近」瀏覽器定位排序
- 🏷 依行政區、免銷單進出場方式篩選
- 🗺 標記自動分群，點選可看詳情、一鍵開 Google 導航
- 📱 手機／桌機、深色模式、鍵盤操作皆支援

## 日常維護

- **每天臺灣時間 00:00 自動更新**，資料有變動才 commit。
- 要立刻更新：repo 上方 **Actions → 每日更新停車場資料 → Run workflow**。
- 每次跑完，Actions 的執行摘要會列出抓到幾筆、幾筆有座標、哪幾筆查不到。

> GitHub 的排程有時會延遲幾分鐘到半小時才觸發，這是正常現象。

## 目前使用免費的 OpenStreetMap 定位

現在座標是用 OpenStreetMap Nominatim（免費、不需金鑰）查出來的，準確度夠用但不是最好。
想換成更準的 Google：

1. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立專案、綁定帳單帳戶
   （每月有 200 美元免費額度，本專案用量遠低於此）。
2. 「API 和服務 → 程式庫」啟用 **Places API** 與 **Geocoding API**。
3. 「憑證 → 建立憑證 → API 金鑰」，複製金鑰。設定限制：
   應用程式限制選「無」或「IP 位址」（金鑰只在 GitHub 伺服器上用，不會出現在網頁裡，
   所以不需要設 HTTP 參照網址限制）；API 限制只勾這兩個 API。
4. 回到這個 repo：**Settings → Secrets and variables → Actions → New repository secret**
   - Name：`GOOGLE_MAPS_API_KEY`
   - Secret：貼上金鑰
5. 刪掉 `parking/cache/geocache.json`，再手動跑一次 workflow，就會用 Google 全部重查一遍。

## 本機測試（選用）

```bash
pip install -r parking/scripts/requirements.txt

python parking/scripts/test_scrape.py     # 離線測試解析邏輯，不連網
python parking/scripts/scrape.py          # 抓表格
python parking/scripts/geocode.py         # 產生 parking/data/parkings.json
python parking/scripts/geocode.py --limit 20   # 只先處理 20 筆，測試用

cd parking && python -m http.server 8000  # 開 http://localhost:8000
```

## 疑難排解

| 症狀 | 處理 |
| --- | --- |
| 網頁顯示「資料載入失敗」 | `parking/data/parkings.json` 還沒產生，去 Actions 手動跑一次。 |
| Actions 在 commit 那步失敗，寫 permission denied | Settings → Actions → General → Workflow permissions 要設成 **Read and write**。 |
| 爬蟲失敗「只解析到 N 筆」 | 對方網站改版了。`scripts/scrape.py` 的 `COLUMN_MAP` 是用表頭文字比對，把新欄位名稱加進去即可。程式刻意在這種情況中止，不會覆蓋掉原本正確的資料。 |
| 某幾個停車場座標偏掉 | 原始資料的「位置」欄常常只有路名沒門牌，只能定位到路段。可以直接編輯 `parking/cache/geocache.json` 裡那一筆的 `lat`／`lng`，之後更新會沿用你改的值。 |
| 地點搜尋沒反應 | 前端用 OpenStreetMap 免費服務，偶爾限流，稍等再試。 |

## 資料來源與免責

- 資料來源：[臺中市停車資訊網 — 身障免銷單服務已上線停車場](https://tcparking.taichung.gov.tw/ParkWeb/Pages/PublicService/LoveCardSchedule)
- 地圖：[OpenStreetMap](https://www.openstreetmap.org/copyright) 貢獻者、[Leaflet](https://leafletjs.com/)
- 座標為地理編碼推估結果，實際位置以現場標示為準；免銷單服務內容一律以臺中市政府交通局公告為準。
- 本專案為民間製作的資料整理工具，非官方網站。
