"""
Checks store.2ndstreet.com.tw for newly-listed Balenciaga bags <= NT$20,000.

Runs headless (Playwright/Chromium) since the site is a client-rendered SPA
(product data is not present in the raw HTML, only after JS executes).

On new matches, creates a GitHub Issue in this repo (which triggers GitHub's
built-in email notification to anyone watching the repo). State is persisted
in state.json and committed back by the workflow.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from parse import find_matching_items

URL = "https://store.2ndstreet.com.tw/V2/Official/SalePageCategory/442464?o=n&m=s&shopId=41320&sortMode=Newest"
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")
PRICE_LIMIT = 20000


def fetch_entries():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60000)
        # give the SPA a moment to paint the list after network idle
        page.wait_for_timeout(2000)
        entries = page.eval_on_selector_all(
            'a[href*="SalePage/Index"]',
            "els => els.map(a => ({href: a.href, text: a.textContent.trim()}))",
        )
        browser.close()
        return entries


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
        lines = [f"發現 {len(new_items)} 個新的 Balenciaga 包(<= NT${PRICE_LIMIT:,}):\n"]
        for it in new_items:
            lines.append(f"- {it['brand']} / {it['category']} — NT${it['price']:,}\n  {it['href']}")
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
