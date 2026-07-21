"""
Parsing logic for 2ndstreet.com.tw product listing entries.
Kept separate from the Playwright fetch code so it can be unit-tested
without a browser.
"""
import re


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

    prices = re.findall(r"NT\$([\d,]+)", text)
    if not prices:
        return None
    price = int(prices[-1].replace(",", ""))

    return {
        "id": item_id,
        "href": href,
        "text": text,
        "brand": brand,
        "category": category,
        "price": price,
    }


def is_matching_bag(item: dict, price_limit: int = 20000) -> bool:
    if item is None:
        return False
    if item["brand"] != "BALENCIAGA":
        return False
    cat = item["category"]
    if "包" not in cat:
        return False
    if "錢包" in cat or "夾" in cat:
        return False
    if item["price"] > price_limit:
        return False
    return True


def find_matching_items(raw_entries, price_limit: int = 20000):
    """raw_entries: list of {"href": ..., "text": ...} as extracted from the page."""
    matches = []
    for e in raw_entries:
        item = parse_entry(e["href"], e["text"])
        if item and is_matching_bag(item, price_limit):
            matches.append(item)
    return matches
