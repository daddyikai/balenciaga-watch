"""
Checks store.2ndstreet.com.tw for newly-listed items <= NT$20,000 from any
brand in parse.WATCHED_BRANDS (any category — not limited to bags).

Runs headless (Playwright/Chromium) since the site is a client-rendered SPA
(product data is not present in the raw HTML, only after JS executes).

Strategy: instead of scanning the site-wide "new arrivals" feed (which only
ever shows the newest ~100 items across ALL brands/categories - with 1000+
items total and constant turnover, a watched-brand item can silently fall
out of that window within a day, especially if a check gets delayed), we
query each watched brand's own "newest" search results. Each brand only
competes against its own listings (typically a few hundred), so items stay
visible far longer and are much less likely to be missed between checks.

On new matches, creates a GitHub Issue in this repo (which triggers GitHub's
built-in email notification to anyone watching the repo). State is persisted
in state.json and committed back by the workflow.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from parse import find_matching_items, WATCHED_BRANDS

SHOP_ID = "41320"
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")
PRICE_LIMIT = 20000


def brand_search_url(brand: str) -> str:
    q = urllib.parse.quote(f'"{brand}"')
    return f"https://store.2ndstreet.com.tw/v2/Search?q={q}&shopId={SHOP_ID}&order=Newest"


def fetch_entries():
    from playwright.sync_api import sync_playwright

    all_entries = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for brand in sorted(WATCHED_BRANDS):
            url = brand_search_url(brand)
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1500)
                entries = page.eval_on_selector_all(
                    'a[href*="SalePage/Index"]',
                    "els => els.map(a => ({href: a.href, text: a.textContent.trim()}))",
                )
                all_entries.extend(entries)
                print(f"DEBUG: brand '{brand}' -> {len(entries)} entries, url={url}", file=sys.stderr)
                if entries:
                    print(f"DEBUG:   first entry: {entries[0]}", file=sys.stderr)
            except Exception as e:
                print(f"WARNING: failed to fetch brand '{brand}': {e}", file=sys.stderr)
        browser.close()

    # de-dupe by href (a brand with an ambiguous name or a re-listed item
    # could otherwise show up more than once across separate brand queries)
    seen_hrefs = set()
    deduped = []
    for e in all_entries:
        if e["href"] not in seen_hrefs:
            seen_hrefs.add(e["href"])
            deduped.append(e)
    return deduped


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"seen_matching_ids": [], "last_checked": None}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def create_github_issue(title, body):
    repo = os.environ["GITHUB_REPOSITORY"]  # "owner/repo", set by Actions
    token = os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    # Manual test path: lets you verify the GitHub Issue -> email pipeline
    # without depending on live site data. Triggered via workflow_dispatch
    # input test_mode=true. Posts as github-actions[bot], same as a real
    # alert, so it actually exercises the notification path (unlike an
    # issue you create yourself, which GitHub won't email you about).
    if os.environ.get("TEST_MODE") == "true":
        title = f"[Balenciaga Watch] 測試通知 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        body = (
            "這是透過 workflow_dispatch test_mode 觸發的測試通知,"
            "確認 Issue 建立 -> email 通知這條路徑正常。\n\n"
            "範例格式:\n"
            "- BALENCIAGA / 後背包 — NT$15,000\n"
            "  https://store.2ndstreet.com.tw/SalePage/Index/12345678"
        )
        print(body)
        if os.environ.get("GITHUB_TOKEN"):
            create_github_issue(title, body)
        else:
            print("(GITHUB_TOKEN not set — skipping issue creation, local run)", file=sys.stderr)
        return

    state = load_state()
    seen = set(state.get("seen_matching_ids", []))

    entries = fetch_entries()
    matches = find_matching_items(entries, price_limit=PRICE_LIMIT)

    new_items = [m for m in matches if m["id"] not in seen]

    # merge all current matches into seen (dedupe)
    for m in matches:
        seen.add(m["id"])
    state["seen_matching_ids"] = sorted(seen)
    state["last_checked"] = datetime.now(timezone.utc).isoformat()

    if new_items:
        lines = [f"發現 {len(new_items)} 個新品項(<= NT${PRICE_LIMIT:,}):\n"]
        for it in new_items:
            price_note = (
                f"約 NT${it['price']:,}(美元換算,僅供參考)"
                if it.get("currency") == "USD"
                else f"NT${it['price']:,}"
            )
            lines.append(f"- {it['brand']} / {it['category']} — {price_note}\n  {it['href']}")
        body = "\n".join(lines)
        print(body)

        if os.environ.get("GITHUB_TOKEN"):
            title = f"[Balenciaga Watch] {len(new_items)} 個新品上架 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            create_github_issue(title, body)
        else:
            print("(GITHUB_TOKEN not set — skipping issue creation, local run)", file=sys.stderr)
    else:
        print(f"No new matching items. Checked at {state['last_checked']}.")

    save_state(state)


if __name__ == "__main__":
    main()
