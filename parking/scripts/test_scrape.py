#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""離線測試：用仿真的假 HTML 驗證 scrape.py 的解析邏輯（不連網）。

假 HTML 刻意重現真實頁面的結構：
第一列是跨欄的大標題（裡面也有「停車場」三個字），第二列才是真正的表頭。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape  # noqa: E402

ROWS = [
    ("1", "陽明大樓地下停車場", "車辨進，多卡通出", "臺中市豐原區陽明街、陽明街66巷"),
    ("2", "臺灣大道市政大樓附屬地下停車場", "車辨進，多卡通出", "臺中市西屯區臺灣大道、文心路、惠中路"),
    ("3", "大誠立體停車場", "車辨進，多卡通出", "台中市中區台灣大道一段、大誠街口"),
    ("4", "中和停車場", "多卡通進出", "臺中市南屯區黎明路一段123巷"),
    ("285", "豐原漆藝館停車場(公所)", "車辨進，多卡通出", "臺中市豐原區水源路1-1號"),
]

HTML = """<html><head><title>臺中市停車管理處開通停車場時程表</title></head><body>
<table><tr><td>版面用表格</td></tr></table>
<table class="MsoNormalTable">
<tr><th colspan="4">身障免銷單服務已上線停車場(115年8月17日更新)</th></tr>
<tr><td>序號</td><td>停車場名稱</td><td>免銷單進出場方式</td><td>位置</td></tr>
%s
</table></body></html>""" % "\n".join(
    "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % r for r in ROWS
)


def main() -> int:
    scrape.MIN_EXPECTED_ROWS = 3
    scrape.fetch = lambda url, retries=4: HTML  # type: ignore[assignment]

    data = scrape.scrape()
    items = data["items"]
    checks = []

    checks.append(("筆數 == 5（標題列與表頭列都不算資料）", data["count"] == 5))
    checks.append(("公告日期轉西元", data["page_updated"] == "2026-08-17"))

    first = items[0]
    checks.append((
        "欄位沒有錯位（名稱不是序號）",
        first["seq"] == "1" and first["name"] == "陽明大樓地下停車場"
        and first["access"] == "車辨進，多卡通出",
    ))
    checks.append(("行政區擷取", first["district"] == "豐原區"))
    checks.append((
        "位置多條路只取第一段當定位地址",
        first["address"] == "臺中市豐原區陽明街" and "、" in first["location"],
    ))

    third = items[2]
    checks.append(("台→臺正規化", third["location"] == "臺中市中區臺灣大道一段、大誠街口"))
    checks.append(("去掉結尾的「口」", third["address"] == "臺中市中區臺灣大道一段"))

    checks.append(("巷弄地址完整保留", items[3]["address"] == "臺中市南屯區黎明路一段123巷"))
    checks.append(("門牌地址完整保留", items[4]["address"] == "臺中市豐原區水源路1-1號"))
    checks.append((
        "不重複加市名",
        all(i["address"].count("臺中市") == 1 for i in items),
    ))
    checks.append((
        "行政區都有辨識出來",
        {i["district"] for i in items} == {"豐原區", "西屯區", "中區", "南屯區"},
    ))
    checks.append(("跳過版面表格", all(i["name"] != "版面用表格" for i in items)))

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

    # 地址候選字串的降級順序
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import geocode  # noqa: E402

    cands = geocode.address_candidates("臺中市豐原區水源路1-1號")
    c2 = geocode.address_candidates("臺中市南屯區黎明路一段123巷")
    checks2 = [
        ("門牌查不到時退成路名", "臺中市豐原區水源路" in cands),
        ("巷弄查不到時退成路段", "臺中市南屯區黎明路一段" in c2),
    ]
    for label, passed in checks2:
        print(("  PASS  " if passed else "  FAIL  ") + label)
        ok = ok and passed

    print("\n" + ("全部通過 ✅" if ok else "有測試失敗 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
