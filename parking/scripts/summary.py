#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本次更新結果印成 GitHub Actions 的執行摘要（Markdown）。"""

import json
from collections import Counter
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "parkings.json"


def main() -> None:
    if not PATH.exists():
        print("## 更新結果\n\n:x: 沒有產生資料檔，請看上方步驟的錯誤訊息。")
        return

    d = json.loads(PATH.read_text(encoding="utf-8"))
    missing = d["count"] - d["geocoded"]

    print("## 更新結果\n")
    print(f"- 停車場總數：**{d['count']}**")
    print(f"- 已取得座標：**{d['geocoded']}**" + (f"（缺 {missing} 筆）" if missing else "（全數完成）"))
    print(f"- 網站公告更新日：{d.get('page_updated') or '未知'}")
    print(f"- 資料產生時間：{d['generated_at']}")

    counts = Counter(i["district"] for i in d["items"])
    print("\n### 行政區分布\n")
    print("| 行政區 | 數量 |")
    print("| --- | ---: |")
    for name, n in counts.most_common():
        print(f"| {name} | {n} |")

    if missing:
        print("\n### 尚未取得座標\n")
        for item in d["items"]:
            if "lat" not in item:
                print(f"- {item['name']}（{item['location']}）")


if __name__ == "__main__":
    main()
