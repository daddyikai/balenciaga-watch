"""
Parsing logic for 2ndstreet.com.tw product listing entries.
Kept separate from the Playwright fetch code so it can be unit-tested
without a browser.
"""
import re

# Brands to watch. Any category counts (bags, shoes, clothing, accessories,
# etc.) — not limited to bags. Matched case-insensitively against the
# brand text as shown on the site.
WATCHED_BRANDS = {
    "BALENCIAGA",
    "TOGA",
    "MAISON MARGIELA",
    "GUIDI",
    "OAKLEY",
    "ACNE STUDIOS",
    "RICK OWENS",
    "PRADA",
    "VETEMENTS",
    "VIVIENNE WESTWOOD",
    "OUR LEGACY",
}

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


def is_matching_item(item: dict, price_limit: int = 20000) -> bool:
    """Any category counts — brand + price is all that matters now."""
    if item is None:
        return False
    if item["brand"].strip().upper() not in WATCHED_BRANDS:
        return False
    if item["price"] > price_limit:
        return False
    return True


def find_matching_items(raw_entries, price_limit: int = 20000):
    """raw_entries: list of {"href": ..., "text": ...} as extracted from the page."""
    matches = []
    for e in raw_entries:
        item = parse_entry(e["href"], e["text"])
        if item and is_matching_item(item, price_limit):
            matches.append(item)
    return matches
