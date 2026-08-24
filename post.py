"""
Post content to a Facebook Page using a saved session.

Reads posts from a text file (3 posts separated by blank lines).
The post containing a URL is always posted first, followed by the rest in order.
A random delay is added between posts to appear natural.

Usage:
    python3 post.py path/to/file.xlsx --account "NOS_PAN_001" --posts path/to/posts.txt
    python3 post.py path/to/file.xlsx --account "NOS_PAN_001" --posts path/to/posts.txt --sheet "BFL Info"

Requirements:
    - A saved session for the account (run login.py --manual first)
"""

import argparse
import os
import random
import re
import sys
import time

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from session_manager import load_session, save_session

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "browser_profiles")

# Delay range between posts (seconds)
MIN_DELAY = 45
MAX_DELAY = 90


def parse_posts(path):
    """Parse posts.txt into a list of {text, url} dicts, URL post first."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    blocks = [b.strip() for b in re.split(r"\n{2,}", raw) if b.strip()]

    posts = []
    url_pattern = re.compile(r"https?://\S+")

    for block in blocks:
        lines = block.splitlines()
        url = None
        text_lines = []
        for line in lines:
            match = url_pattern.search(line)
            if match and line.strip() == match.group():
                url = line.strip()
            else:
                text_lines.append(line)
        posts.append({"text": "\n".join(text_lines).strip(), "url": url})

    # Merge standalone URL-only blocks into adjacent text blocks
    merged = []
    i = 0
    while i < len(posts):
        post = posts[i]
        if post["url"] and not post["text"]:
            # Attach to next text block if available, else to previous
            if i + 1 < len(posts) and not posts[i + 1]["url"]:
                posts[i + 1]["url"] = post["url"]
            elif merged and not merged[-1]["url"]:
                merged[-1]["url"] = post["url"]
            else:
                merged.append(post)
        else:
            merged.append(post)
        i += 1

    # Put URL post first, preserve order of the rest
    url_posts  = [p for p in merged if p["url"]]
    text_posts = [p for p in merged if not p["url"]]
    return url_posts + text_posts


def human_type(page, text, min_delay=0.04, max_delay=0.14):
    for char in text:
        page.keyboard.type(char)
        time.sleep(random.uniform(min_delay, max_delay))


def human_pause(min_s=0.8, max_s=2.0):
    time.sleep(random.uniform(min_s, max_s))


def open_composer(page):
    """Click 'What's on your mind?' in the main feed only, then wait for the dialog."""
    page.evaluate("window.scrollTo(0, 0)")
    human_pause(1.0, 1.5)

    for selector in [
        "div[role='main'] div[role='button']:has-text(\"What's on your mind?\")",
        "div[role='main'] div[aria-label=\"What's on your mind?\"]",
        "div[role='main'] span:has-text(\"What's on your mind?\")",
    ]:
        try:
            el = page.locator(selector).first
            if el.is_visible():
                el.click()
                human_pause(2.0, 3.0)
                # Wait for the Create post dialog to appear
                page.wait_for_selector("div[role='dialog']", timeout=8000)
                human_pause(1.0, 1.5)
                return True
        except Exception:
            continue
    # Save a screenshot so we can see what's on the page
    try:
        page.screenshot(path=os.path.join(os.path.dirname(__file__), "debug_composer.png"))
        print("Composer not found. Screenshot saved to debug_composer.png")
    except Exception:
        pass
    return False


def submit_post(page):
    """Dismiss any autocomplete, then click Next/Post inside the dialog."""
    # Dismiss hashtag/mention autocomplete if visible
    page.keyboard.press("Escape")
    human_pause(0.3, 0.6)

    # Facebook Pages show "Next" instead of "Post"
    for name in [r"^Next$", r"^Post$"]:
        try:
            btn = page.locator("div[role='dialog']").get_by_role(
                "button", name=re.compile(name, re.I)
            ).last
            if btn.is_visible():
                btn.click()
                return True
        except Exception:
            continue

    for selector in [
        "div[role='dialog'] div[aria-label='Next'][role='button']",
        "div[role='dialog'] div[aria-label='Post'][role='button']",
        "div[role='dialog'] [data-testid='react-composer-post-button']",
    ]:
        try:
            el = page.locator(selector).last
            if el.is_visible():
                el.click()
                return True
        except Exception:
            continue

    return False


def publish_post(page, post, index, page_url="https://www.facebook.com/"):
    print(f"\n── Post {index + 1} {'(with link)' if post['url'] else ''} ──")

    page.goto(page_url, wait_until="domcontentloaded")
    human_pause(2.5, 4.0)

    print("Opening composer...")
    if not open_composer(page):
        print("Could not find composer. Skipping this post.")
        return False

    # Type inside the dialog textbox
    print("Typing post content...")
    try:
        textbox = page.locator("div[role='dialog'] div[role='textbox'][contenteditable='true']").first
        textbox.click()
        human_pause(0.5, 1.0)
    except Exception:
        pass

    human_type(page, post["text"])

    if post["url"]:
        human_pause(0.5, 1.2)
        print(f"Adding URL: {post['url']}")
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        human_type(page, post["url"])
        print("Waiting for link preview to load...")
        human_pause(5.0, 7.0)

    human_pause(1.0, 2.0)

    print("Submitting post...")
    if not submit_post(page):
        print("Could not find Next/Post button. Please click it manually.")
        human_pause(20.0, 20.0)
        return False

    page.wait_for_load_state("domcontentloaded")
    human_pause(2.5, 4.0)
    print(f"Post {index + 1} published.")
    return True


def load_account_name(path, account_name, sheet_name):
    """Just validates the account exists in the sheet."""
    from login import load_credentials, SHEET_LAYOUTS
    return load_credentials(path, account_name, sheet_name)


def run(path, account_name, sheet_name, posts_path):
    cookies = load_session(account_name)
    if not cookies:
        print(f"No saved session for '{account_name}'.")
        print(f"Run first:  python3 login.py \"{path}\" --account \"{account_name}\" --manual")
        sys.exit(1)

    posts = parse_posts(posts_path)
    print(f"Loaded {len(posts)} posts from {posts_path}")
    for i, p in enumerate(posts):
        preview = p["text"][:60].replace("\n", " ")
        print(f"  {i+1}. {'[LINK] ' if p['url'] else ''}  {preview}...")

    profile_safe = account_name.replace("/", "_").replace(" ", "_")
    user_data_dir = os.path.join(PROFILES_DIR, profile_safe)
    os.makedirs(user_data_dir, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print("\nRestoring session...")
        context.add_cookies(cookies)
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        human_pause(2.0, 3.0)

        if "login" in page.url:
            print("Session expired. Re-run login.py --manual first.")
            context.close()
            sys.exit(1)

        # Try Switch Now button; if not found, use the known fanpage URL from last session
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        human_pause(2.0, 3.0)

        switched = False
        try:
            # Look for Switch Now in any form (button or link)
            for locator in [
                page.get_by_role("button", name=re.compile(r"switch now", re.I)),
                page.get_by_role("link", name=re.compile(r"switch now", re.I)),
                page.locator("a:has-text('Switch Now'), div[role='button']:has-text('Switch Now')"),
            ]:
                if locator.count() > 0:
                    print("Switching to page...")
                    locator.first.click()
                    page.wait_for_load_state("domcontentloaded")
                    human_pause(2.0, 3.0)
                    switched = True
                    break
        except Exception:
            pass

        if not switched:
            print("Switch Now not found — you may need to switch manually in the browser,")
            print("or the session is already on the fanpage. Continuing with current URL.")

        active_page_url = page.url
        print(f"Active page URL: {active_page_url}")
        print("Session active. Starting to post...\n")

        for i, post in enumerate(posts):
            success = publish_post(page, post, i, active_page_url)

            if success and i < len(posts) - 1:
                delay = random.randint(MIN_DELAY, MAX_DELAY)
                print(f"Waiting {delay}s before next post...")
                time.sleep(delay)

        save_session(account_name, context.cookies())
        print("\nAll posts done. Session saved.")

        print("Browser is open. Close it when done.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass

        context.close()


def main():
    parser = argparse.ArgumentParser(description="Post content to a Facebook Page.")
    parser.add_argument("file",    help="Path to the .xlsx workbook")
    parser.add_argument("--account", required=True, help="Account name (e.g. NOS_PAN_001)")
    parser.add_argument("--posts",   required=True, help="Path to posts.txt")
    parser.add_argument("--sheet",   default="New VProfiles for BFL", help="Sheet name")
    args = parser.parse_args()

    run(args.file, args.account, args.sheet, args.posts)


if __name__ == "__main__":
    main()
