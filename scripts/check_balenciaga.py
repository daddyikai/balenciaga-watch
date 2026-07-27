"""
Checks store.2ndstreet.com.tw for two independent things and creates a
separate GitHub Issue (-> email notification) for each one that has news:

需求一 (any_new_arrival): ANY newly-listed item on the whole site, any
brand, any category, any price. Uses the shared "新品上架"/new-arrivals
category feed, which only ever shows the newest ~100 items site-wide. That
is fine here because this requirement only cares about "what's new since
last check", checked every 15 minutes - it will never need to look past
the first page.

需求二 (balenciaga_bag): ONLY BALENCIAGA-brand items whose category text
contains "包" (i.e. any kind of bag/wallet/pouch), priced at or below
PRICE_LIMIT. Uses a BALENCIAGA-only "newest" search feed so items don't
age out between checks the way they would on the shared feed.

Runs headless (Playwright/Chromium) since the site is a client-rendered SPA
(product data is not present in the raw HTML, only after JS executes).

State (seen ids for each requirement, kept separately) is persisted in
state.json and committed back by the workflow.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from parse import find_new_arrivals, find_balenciaga_bags

SHOP_ID = "41320"
NEW_ARRIVALS_CATEGORY_ID = "442464"
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")
PRICE_LIMIT = 20000


def new_arrivals_url() -> str:
    # NOTE: must include the "/v2/official" prefix - the old bare
    # "/SalePageCategory/..." path 404s (site was restructured at some
    # point). Verified working: https://store.2ndstreet.com.tw/v2/official/SalePageCategory/442464?sortMode=Newest
    return (
        f"https://store.2ndstreet.com.tw/v2/official/SalePageCategory/{NEW_ARRIVALS_CATEGORY_ID}"
        f"?sortMode=Newest"
    )


def brand_search_url(brand: str) -> str:
    q = urllib.parse.quote(f'"{brand}"')
    return f"https://store.2ndstreet.com.tw/v2/Search?q={q}&shopId={SHOP_ID}&order=Newest"


def _extract_entries(page, url):
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    entries = page.eval_on_selector_all(
        'a[href*="SalePage/Index"]',
        "els => els.map(a => ({href: a.href, text: a.textContent.trim()}))",
    )
    return entries


def fetch_all():
    from playwright.sync_api import sync_playwright

    new_arrival_entries = []
    balenciaga_entries = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        try:
            new_arrival_entries = _extract_entries(page, new_arrivals_url())
            print(f"DEBUG: new-arrivals feed -> {len(new_arrival_entries)} entries", file=sys.stderr)
        except Exception as e:
            print(f"WARNING: failed to fetch new-arrivals feed: {e}", file=sys.stderr)

        try:
            balenciaga_entries = _extract_entries(page, brand_search_url("BALENCIAGA"))
            print(f"DEBUG: balenciaga search -> {len(balenciaga_entries)} entries", file=sys.stderr)
        except Exception as e:
            print(f"WARNING: failed to fetch balenciaga search: {e}", file=sys.stderr)

        browser.close()

    return new_arrival_entries, balenciaga_entries


def load_state():
    default = {
        "seen_new_arrival_ids": [],
        "seen_balenciaga_bag_ids": [],
        "last_checked": None,
    }
    if not os.path.exists(STATE_PATH):
        return default
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    # One-time migration from the old single-list schema: seed both new
    # requirement's "seen" sets with everything already reported before,
    # so we don't re-notify a backlog of stuff you've already seen.
    legacy_seen = state.get("seen_matching_ids", [])
    if "seen_new_arrival_ids" not in state:
        state["seen_new_arrival_ids"] = list(legacy_seen)
    if "seen_balenciaga_bag_ids" not in state:
        state["seen_balenciaga_bag_ids"] = list(legacy_seen)
    state.pop("seen_matching_ids", None)
    return state


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


def _price_note(it):
    return (
        f"約 NT${it['price']:,}(美元換算,僅供參考)"
        if it.get("currency") == "USD"
        else f"NT${it['price']:,}"
    )


def main():
    # Manual test path: lets you verify the GitHub Issue -> email pipeline
    # without depending on live site data. Triggered via workflow_dispatch
    # input test_mode=true. Posts as github-actions[bot], same as a real
    # alert, so it actually exercises the notification path (unlike an
    # issue you create yourself, which GitHub won't email you about).
    if os.environ.get("TEST_MODE") == "true":
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        title = f"[Watch] 測試通知 {ts}"
        body = (
            "這是透過 workflow_dispatch test_mode 觸發的測試通知,"
            "確認 Issue 建立 -> email 通知這條路徑正常。\n\n"
            "範例格式:\n"
            "需求一(任何新品上架): BALENCIAGA / 後背包 — NT$15,000\n"
            "需求二(Balenciaga包款<=2萬): BALENCIAGA / 側背包 — NT$12,000\n"
            "https://store.2ndstreet.com.tw/SalePage/Index/12345678"
        )
        print(body)
        if os.environ.get("GITHUB_TOKEN"):
            create_github_issue(title, body)
        else:
            print("(GITHUB_TOKEN not set — skipping issue creation, local run)", file=sys.stderr)
        return

    state = load_state()
    seen_new = set(state.get("seen_new_arrival_ids", []))
    seen_bags = set(state.get("seen_balenciaga_bag_ids", []))

    new_arrival_entries, balenciaga_entries = fetch_all()

    all_new_arrivals = find_new_arrivals(new_arrival_entries)
    all_bags = find_balenciaga_bags(balenciaga_entries, price_limit=PRICE_LIMIT)

    fresh_new_arrivals = [it for it in all_new_arrivals if it["id"] not in seen_new]
    fresh_bags = [it for it in all_bags if it["id"] not in seen_bags]

    for it in all_new_arrivals:
        seen_new.add(it["id"])
    for it in all_bags:
        seen_bags.add(it["id"])

    state["seen_new_arrival_ids"] = sorted(seen_new)
    state["seen_balenciaga_bag_ids"] = sorted(seen_bags)
    state["last_checked"] = datetime.now(timezone.utc).isoformat()

    has_token = bool(os.environ.get("GITHUB_TOKEN"))
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # 需求一: 任何新品上架,不分品牌不分價格
    if fresh_new_arrivals:
        lines = [f"【需求一:新品上架】發現 {len(fresh_new_arrivals)} 個新上架品項(不分品牌/價格):\n"]
        for it in fresh_new_arrivals:
            lines.append(f"- {it['brand']} / {it['category']} — {_price_note(it)}\n  {it['href']}")
        body = "\n".join(lines)
        print(body)
        if has_token:
            title = f"[新品上架] {len(fresh_new_arrivals)} 個新品 {ts}"
            create_github_issue(title, body)
        else:
            print("(GITHUB_TOKEN not set — skipping issue creation, local run)", file=sys.stderr)
    else:
        print("需求一: 沒有新上架品項。")

    # 需求二: 僅 Balenciaga 包款 <= NT$20,000
    if fresh_bags:
        lines = [f"【需求二:Balenciaga包款】發現 {len(fresh_bags)} 個新品項(<= NT${PRICE_LIMIT:,}):\n"]
        for it in fresh_bags:
            lines.append(f"- {it['brand']} / {it['category']} — {_price_note(it)}\n  {it['href']}")
        body = "\n".join(lines)
        print(body)
        if has_token:
            title = f"[Balenciaga包款] {len(fresh_bags)} 個新品(<=NT${PRICE_LIMIT:,}) {ts}"
            create_github_issue(title, body)
        else:
            print("(GITHUB_TOKEN not set — skipping issue creation, local run)", file=sys.stderr)
    else:
        print("需求二: 沒有新的 Balenciaga 包款。")

    save_state(state)


if __name__ == "__main__":
    main()
