"""
Parsing logic for 2ndstreet.com.tw product listing entries.
Kept separate from the Playwright fetch code so it can be unit-tested
without a browser.

Two independent requirements are supported:
1. find_new_arrivals(): ANY newly-listed item, any brand, any category,
   any price. No filtering at all beyond skipping sold-out/unparseable
   entries. Meant to be run against the site-wide "new arrivals" feed.
2. find_balenciaga_bags(): ONLY BALENCIAGA-brand items whose category
   looks like a bag (category text contains "包"), priced at or below
   price_limit. Meant to be run against a BALENCIAGA-only search feed.
"""
import re

# The site auto-picks a display currency based on the visitor's apparent
# location. A browser session in Taiwan sees "NT$"; a GitHub Actions runner
# (US/international IPs) sees "US$" instead - same item, no NT$ price shown
# at all. We can't reliably force the site back to TWD from a headless
# runner, so instead we accept either currency and convert USD to an
# approximate TWD figure for the price-limit check. The rate is a rough
# approximation (rounded), not a live FX rate - fine for a "<= NT$X" cutoff,
# not fine for precise pricing.
USD_TO_TWD_RATE = 32.5


def extract_id(href: str):
    m = re.search(r"SalePage/Index/(\d+)", href)
    return int(m.group(1)) if m else None


def parse_entry(href: str, text: str):
    """Parse one <a> entry's href+text into a structured dict, or None if
    it should be skipped (sold out / unparseable)."""
    if "已售完" in text:
        return None

    item_id = extract_id(href)
    if item_id is None:
        return None

    # Strip known leading badges (only "已售完" matters for skipping, but
    # other badges like 已收藏 can also prefix the brand block).
    body = text
    if "】" in body:
        body = body.split("】", 1)[1]
    else:
        return None

    parts = body.split("/")
    if len(parts) < 2:
        return None

    brand = parts[0].strip()
    category = parts[1].strip()

    twd_prices = re.findall(r"NT\$([\d,]+)", text)
    if twd_prices:
        price = int(twd_prices[-1].replace(",", ""))
        currency = "TWD"
    else:
        usd_prices = re.findall(r"US\$([\d,.]+)", text)
        if not usd_prices:
            return None
        usd_amount = float(usd_prices[-1].replace(",", ""))
        price = round(usd_amount * USD_TO_TWD_RATE)
        currency = "USD"

    return {
        "id": item_id,
        "href": href,
        "text": text,
        "brand": brand,
        "category": category,
        "price": price,
        "currency": currency,
    }


def is_balenciaga_bag(item: dict, price_limit: int = 20000) -> bool:
    """需求二: 僅 BALENCIAGA 包款, price <= price_limit."""
    if item is None:
        return False
    if item["brand"].strip().upper() != "BALENCIAGA":
        return False
    if "包" not in item["category"]:
        return False
    if item["price"] > price_limit:
        return False
    return True


def find_new_arrivals(raw_entries):
    """需求一: 任何新上架品項,不分品牌、不分價格 (只跳過已售完/無法解析的)."""
    items = []
    for e in raw_entries:
        item = parse_entry(e["href"], e["text"])
        if item:
            items.append(item)
    return items


def find_balenciaga_bags(raw_entries, price_limit: int = 20000):
    """需求二: 僅 BALENCIAGA 包款, <= price_limit."""
    items = []
    for e in raw_entries:
        item = parse_entry(e["href"], e["text"])
        if item and is_balenciaga_bag(item, price_limit):
            items.append(item)
    return items
