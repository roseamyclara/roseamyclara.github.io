#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""離線測試：用假 HTML 驗證 scrape.py 的解析邏輯（不連網）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape  # noqa: E402

ROWS = [
    ("1", "陽明大樓地下停車場", "車辨進，多卡通出", "豐原區陽明街"),
    ("2", "臺灣大道市政大樓附屬地下停車場", "車辨進，多卡通出", "西屯區臺灣大道"),
    ("3", "大誠立體停車場", "車辨進，多卡通出", "中區台灣大道一段"),
    ("4", "漢口立體停車場", "車辨進，多卡通出", "西屯區寧夏路80號"),
    ("5", "十甲停車場", "多卡通進出", "東區二聖街"),
]

HTML = """<html><head><title>身障免銷單服務已上線停車場</title></head><body>
<div>導覽列</div>
<table><tr><td>版面用表格</td></tr></table>
<h2>身障免銷單服務已上線停車場(115年8月17日更新)</h2>
<table class="whatever">
<thead><tr><th>序號</th><th>停車場名稱</th><th>免銷單進出場方式</th><th>位置</th></tr></thead>
<tbody>
%s
</tbody></table></body></html>""" % "\n".join(
    "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % r for r in ROWS
)


def main() -> int:
    scrape.MIN_EXPECTED_ROWS = 3
    scrape.fetch = lambda url, retries=4: HTML  # type: ignore[assignment]

    data = scrape.scrape()
    checks = []

    checks.append(("筆數 == 5", data["count"] == 5))
    checks.append(("公告日期轉西元", data["page_updated"] == "2026-08-17"))

    first = data["items"][0]
    checks.append(("欄位對應正確", first["name"] == "陽明大樓地下停車場"
                   and first["access"] == "車辨進，多卡通出"))
    checks.append(("行政區擷取", first["district"] == "豐原區"))
    checks.append(("地址補上市名", first["address"] == "臺中市豐原區陽明街"))

    third = data["items"][2]
    checks.append(("台→臺正規化", third["location"] == "中區臺灣大道一段"))

    districts = {i["district"] for i in data["items"]}
    checks.append(("多行政區辨識", districts == {"豐原區", "西屯區", "中區", "東區"}))
    checks.append(("跳過版面表格", all(i["name"] != "版面用表格" for i in data["items"])))

    ok = True
    for label, passed in checks:
        print(("  PASS  " if passed else "  FAIL  ") + label)
        ok = ok and passed

    # 健全性門檻要能擋下壞資料
    scrape.MIN_EXPECTED_ROWS = 50
    try:
        scrape.scrape()
        print("  FAIL  筆數過少時應中止")
        ok = False
    except RuntimeError:
        print("  PASS  筆數過少時中止")

    print("\n" + ("全部通過 ✅" if ok else "有測試失敗 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
