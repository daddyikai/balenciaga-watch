#!/usr/bin/env python3
"""
weekly_report.py

放進你 balenciaga-watch repo 的 scripts/ 資料夾, 跟現有的 parse.py 放一起
(會直接 import parse.py 的 WATCHED_BRANDS, 確保監測品牌清單只有一份來源)。

每週跑一次(建議週六早上 8 點 Asia/Taipei), 彙整過去 7 天 WATCHED_BRANDS 這些品牌
在 2ndstreet.com.tw「新品上架」分類裡的:
  1. 各品牌發布品項頻率
  2. 價位分布
  3. 品類分布
  4. 發布時間點(星期 x 小時)
並根據統計結果產出「怎麼優化 / 第一時間搶好品項」的具體建議, 寄一封 email。

資料來源: 2ndstreet 背後的 91App GraphQL API (公開, 不需登入)。
不需要瀏覽器/Playwright, 直接用 requests 打 API, 跑起來比現有的
check_balenciaga.py 快很多。

需要的 GitHub Secrets (Settings -> Secrets and variables -> Actions):
  GMAIL_ADDRESS       寄件用的 Gmail 帳號
  GMAIL_APP_PASSWORD  該帳號的應用程式專用密碼(16碼, myaccount.google.com/apppasswords)

收件人預設寫死在 REPORT_RECIPIENT, 也可以用環境變數覆蓋。
"""

import json
import os
import re
import smtplib
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from statistics import mean, median
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from parse import WATCHED_BRANDS  # 跟現有監測腳本共用同一份品牌清單

SHOP_ID = 41320
CATEGORY_ID = 442464
GRAPHQL_URL = "https://fts-api.91app.com/pythia-cdn/graphql"
PAGE_SIZE = 200
MAX_PAGES = 20
LOOKBACK_DAYS = 7
TAIPEI = timezone(timedelta(hours=8))
REPORT_RECIPIENT = os.environ.get("REPORT_RECIPIENT", "yikai0825@gmail.com")

QUERY = """
query cms_shopCategory($shopId: Int!, $categoryId: Int!, $startIndex: Int!, $fetchCount: Int!, $orderBy: String) {
  shopCategory(shopId: $shopId, categoryId: $categoryId) {
    salePageList(startIndex: $startIndex, maxCount: $fetchCount, orderBy: $orderBy) {
      salePageList {
        salePageId
        title
        price
        isSoldOut
        listingStartDateTime
      }
      totalSize
    }
  }
}
""".strip()

BRAND_CATEGORY_RE = re.compile(r"^【[^】]*】(.*)$")


def fetch_page(start_index: int):
    variables = {
        "shopId": SHOP_ID,
        "categoryId": CATEGORY_ID,
        "startIndex": start_index,
        "fetchCount": PAGE_SIZE,
        "orderBy": "Newest",
    }
    params = {
        "shopId": SHOP_ID,
        "lang": "zh-TW",
        "query": QUERY,
        "operationName": "cms_shopCategory",
        "variables": json.dumps(variables, ensure_ascii=False),
    }
    url = f"{GRAPHQL_URL}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; balenciaga-weekly-report/1.0)",
            "Referer": "https://store.2ndstreet.com.tw/",
        },
    )
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return data["data"]["shopCategory"]["salePageList"]["salePageList"]


def parse_title(title: str):
    m = BRAND_CATEGORY_RE.match(title)
    rest = m.group(1) if m else title
    parts = rest.split("/")
    brand = parts[0].strip() if parts else ""
    category = parts[1].strip() if len(parts) > 1 else ""
    return brand, category


def fetch_last_n_days(days=LOOKBACK_DAYS):
    cutoff_ms = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
    items = []
    for page in range(MAX_PAGES):
        batch = fetch_page(page * PAGE_SIZE)
        if not batch:
            break
        items.extend(batch)
        oldest_in_batch = min(b["listingStartDateTime"] for b in batch)
        if oldest_in_batch < cutoff_ms:
            break
    return [it for it in items if it["listingStartDateTime"] >= cutoff_ms]


def build_dataset(raw_items):
    rows = []
    for it in raw_items:
        brand, category = parse_title(it["title"])
        dt_taipei = datetime.fromtimestamp(it["listingStartDateTime"] / 1000, tz=TAIPEI)
        rows.append({
            "id": it["salePageId"],
            "title": it["title"],
            "brand": brand,
            "category": category,
            "price": it["price"],
            "is_sold_out": it["isSoldOut"],
            "listed_at": dt_taipei,
        })
    return rows


PRICE_BUCKETS = [
    ("< 5,000", lambda p: p < 5000),
    ("5,000-10,000", lambda p: 5000 <= p < 10000),
    ("10,000-20,000", lambda p: 10000 <= p < 20000),
    ("20,000-50,000", lambda p: 20000 <= p < 50000),
    ("50,000+", lambda p: p >= 50000),
]

WEEKDAY_NAMES_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def analyze(rows):
    watched_rows = [r for r in rows if r["brand"].strip().upper() in WATCHED_BRANDS]

    brand_counts = Counter(r["brand"] for r in watched_rows)
    category_counts = Counter(r["category"] for r in watched_rows)

    prices = [r["price"] for r in watched_rows if r["price"]]
    price_stats = {
        "count": len(prices),
        "min": min(prices) if prices else None,
        "median": median(prices) if prices else None,
        "mean": round(mean(prices), 0) if prices else None,
        "max": max(prices) if prices else None,
    }
    price_bucket_counts = Counter()
    for p in prices:
        for label, cond in PRICE_BUCKETS:
            if cond(p):
                price_bucket_counts[label] += 1
                break

    # per-brand sold-out rate (velocity proxy)
    sold_out_rate = {}
    for brand in brand_counts:
        brand_items = [r for r in watched_rows if r["brand"] == brand]
        sold = sum(1 for r in brand_items if r["is_sold_out"])
        sold_out_rate[brand] = sold / len(brand_items) if brand_items else 0

    weekday_counts = Counter(r["listed_at"].weekday() for r in watched_rows)
    hour_counts = Counter(r["listed_at"].hour for r in watched_rows)

    return {
        "watched_rows": watched_rows,
        "brand_counts": brand_counts,
        "category_counts": category_counts,
        "price_stats": price_stats,
        "price_bucket_counts": price_bucket_counts,
        "sold_out_rate": sold_out_rate,
        "weekday_counts": weekday_counts,
        "hour_counts": hour_counts,
    }


def format_report(analysis, period_days=LOOKBACK_DAYS):
    a = analysis
    lines = []
    now_str = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")
    lines.append(f"2ndstreet 監測品牌週報 — 產出時間 {now_str} (過去 {period_days} 天)")
    lines.append("=" * 50)
    lines.append(f"監測品牌: {', '.join(sorted(WATCHED_BRANDS))}")
    lines.append(f"本週符合品牌的新上架總數 (所有品類): {len(a['watched_rows'])} 件")
    lines.append("")

    lines.append("1. 各品牌發布品項頻率")
    lines.append("-" * 30)
    if a["brand_counts"]:
        for brand, cnt in a["brand_counts"].most_common():
            rate = a["sold_out_rate"].get(brand, 0) * 100
            lines.append(f"  {brand:<20} {cnt:>3} 件   已售完比例 {rate:.0f}%")
    else:
        lines.append("  (本週沒有監測品牌的新上架)")
    lines.append("")

    lines.append("2. 價位")
    lines.append("-" * 30)
    ps = a["price_stats"]
    if ps["count"]:
        lines.append(f"  件數 {ps['count']} / 最低 NT${ps['min']:,.0f} / 中位數 NT${ps['median']:,.0f} "
                      f"/ 平均 NT${ps['mean']:,.0f} / 最高 NT${ps['max']:,.0f}")
        lines.append("  價格區間分布:")
        for label, _ in PRICE_BUCKETS:
            lines.append(f"    {label:<15} {a['price_bucket_counts'].get(label, 0)} 件")
    else:
        lines.append("  (無價格資料)")
    lines.append("")

    lines.append("3. 品類")
    lines.append("-" * 30)
    for cat, cnt in a["category_counts"].most_common(15):
        lines.append(f"  {cat or '(未分類)':<15} {cnt} 件")
    lines.append("")

    lines.append("4. 發布的時間點")
    lines.append("-" * 30)
    lines.append("  依星期:")
    for i, name in enumerate(WEEKDAY_NAMES_ZH):
        lines.append(f"    {name}: {a['weekday_counts'].get(i, 0)} 件")
    lines.append("  依小時(Asia/Taipei, 0-23):")
    busiest_hours = sorted(a["hour_counts"].items(), key=lambda kv: -kv[1])[:5]
    for hour, cnt in busiest_hours:
        lines.append(f"    {hour:02d}:00-{hour:02d}:59  {cnt} 件")
    lines.append("")

    lines.append("5. 優化建議")
    lines.append("-" * 30)
    lines.extend(build_recommendations(a))

    return "\n".join(lines)


def build_recommendations(a):
    recs = []
    if a["weekday_counts"]:
        top_weekday = max(a["weekday_counts"].items(), key=lambda kv: kv[1])
        recs.append(f"- 上架量最高的是{WEEKDAY_NAMES_ZH[top_weekday[0]]}({top_weekday[1]} 件),建議這天加強巡邏頻率。")
    if a["hour_counts"]:
        top_hours = sorted(a["hour_counts"].items(), key=lambda kv: -kv[1])[:3]
        hour_str = "、".join(f"{h:02d}:00" for h, _ in top_hours)
        recs.append(f"- 上架尖峰時段集中在 {hour_str} 前後,建議把排程/巡邏頻率在這些時段拉高(例如改成每 5-10 分鐘檢查一次)。")
    if a["sold_out_rate"]:
        fastest = sorted(a["sold_out_rate"].items(), key=lambda kv: -kv[1])[:3]
        fastest = [f"{b}({r*100:.0f}%)" for b, r in fastest if r > 0]
        if fastest:
            recs.append(f"- 已售完比例最高的品牌: {', '.join(fastest)},這些牌子出現新品要優先、快速決定,晚了容易被搶先。")
    if a["brand_counts"]:
        top_brand = a["brand_counts"].most_common(1)[0]
        recs.append(f"- 監測品牌中「{top_brand[0]}」上架量最大({top_brand[1]} 件),但件數多不代表好貨多,建議搭配價位區間一起篩選,避免被高頻但普通的品項洗掉注意力。")
    if a["price_bucket_counts"]:
        top_bucket = a["price_bucket_counts"].most_common(1)[0]
        recs.append(f"- 價格集中在「{top_bucket[0]}」區間({top_bucket[1]} 件),若預算鎖定特定區間,可以只針對該區間設定額外提醒,減少雜訊。")
    if not recs:
        recs.append("- 本週監測品牌新上架數量太少,暫時看不出明顯規律,建議再累積 1-2 週資料後參考。")
    return recs


def send_email(body: str):
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_address or not app_password:
        print("錯誤: 未設定 GMAIL_ADDRESS / GMAIL_APP_PASSWORD, 無法寄信。", file=sys.stderr)
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"2ndstreet 監測品牌週報 {datetime.now(TAIPEI).strftime('%Y-%m-%d')}"
    msg["From"] = gmail_address
    msg["To"] = REPORT_RECIPIENT

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, app_password)
        server.sendmail(gmail_address, [REPORT_RECIPIENT], msg.as_string())
    return True


def main():
    raw_items = fetch_last_n_days()
    rows = build_dataset(raw_items)
    analysis = analyze(rows)
    report = format_report(analysis)
    print(report)

    ok = send_email(report)
    if ok:
        print(f"\n已寄出至 {REPORT_RECIPIENT}")
    else:
        print("\n未寄出(缺少 Gmail 憑證環境變數)", file=sys.stderr)


if __name__ == "__main__":
    main()
