"""
Open a Meta/Facebook account from the spreadsheet in a browser window.

Two modes:

  --manual  (first time or when session expires)
      Opens a browser at the Facebook login page.
      You log in yourself — handles any CAPTCHAs, 2FA, checkpoints.
      Once logged in the script detects it, saves the session, and
      navigates to the profile.

  (no flag)  (every time after)
      Loads the saved session and opens the profile directly.
      No login page, no CAPTCHA. If the session has expired it will
      tell you to re-run with --manual.

Usage:
    First time:
        python3 login.py path/to/file.xlsx --account "NOS_PAN_001" --manual

    Every time after:
        python3 login.py path/to/file.xlsx --account "NOS_PAN_001"

    Force a fresh manual login (clear old session):
        python3 login.py path/to/file.xlsx --account "NOS_PAN_001" --manual --clear-session
"""

import argparse
import os
import sys
import time

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from session_manager import delete_session, load_session, save_session

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "browser_profiles")

SHEET_LAYOUTS = {
    "New VProfiles for BFL": {
        "start_row": 2,
        "name_col":     3,   # C
        "uid_col":      4,   # D
        "password_col": 5,   # E
        "fa_col":       6,   # F
        "email_col":    7,   # G
        "recovery_col": 8,   # H
        "provider_col": 9,   # I
    },
    "BFL Info": {
        "start_row": 3,
        "name_col":     2,   # B
        "uid_col":      5,   # E
        "password_col": 6,   # F
        "fa_col":       7,   # G
        "email_col":    None,
        "recovery_col": 8,   # H
        "provider_col": 9,   # I
    },
}


def normalize(value):
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def load_credentials(path, account_name, sheet_name):
    try:
        wb = load_workbook(path, data_only=True)
    except FileNotFoundError:
        print(f"Error: file not found at '{path}'.")
        sys.exit(2)

    if sheet_name not in wb.sheetnames:
        print(f"Error: sheet '{sheet_name}' not found. Available: {wb.sheetnames}")
        sys.exit(2)

    if sheet_name not in SHEET_LAYOUTS:
        print(f"Error: no layout configured for sheet '{sheet_name}'.")
        sys.exit(2)

    layout = SHEET_LAYOUTS[sheet_name]
    ws = wb[sheet_name]

    for row_idx in range(layout["start_row"], ws.max_row + 1):
        name = normalize(ws.cell(row=row_idx, column=layout["name_col"]).value)
        if name == account_name:
            return {
                "name": name,
                "uid":  normalize(ws.cell(row=row_idx, column=layout["uid_col"]).value),
            }

    print(f"Error: account '{account_name}' not found in sheet '{sheet_name}'.")
    sys.exit(2)


def profile_dir(account_name):
    safe = account_name.replace("/", "_").replace(" ", "_")
    path = os.path.join(PROFILES_DIR, safe)
    os.makedirs(path, exist_ok=True)
    return path


def make_context(p, account_name):
    return p.chromium.launch_persistent_context(
        user_data_dir=profile_dir(account_name),
        headless=False,
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        args=["--disable-blink-features=AutomationControlled"],
    )


def manual_login(context, account_name):
    """Open the login page and wait for the user to log in manually."""
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    print("Opening Facebook login page...")
    print("→ Log in as usual (email, password, 2FA, any checkpoints).")
    print("→ The script will detect when you're done and save your session automatically.\n")

    page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")

    # Poll until we leave the login page (up to 5 minutes)
    timeout = 300
    start = time.time()
    while time.time() - start < timeout:
        current_url = page.url
        if "login" not in current_url and "checkpoint" not in current_url:
            print(f"Login detected. Saving session...")
            save_session(account_name, context.cookies())
            print("Session saved.")
            return page
        time.sleep(1)

    print("Timed out waiting for login. Please try again.")
    sys.exit(1)


def restore_session(context, account_name):
    """Load saved cookies and check if the session is still valid."""
    cookies = load_session(account_name)
    if not cookies:
        return None, False

    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    print("Loading saved session...")
    context.add_cookies(cookies)
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    time.sleep(2)

    if "login" in page.url:
        print("Session has expired.")
        return page, False

    print("Session restored successfully.")
    save_session(account_name, context.cookies())  # refresh saved cookies
    return page, True


def open_account(path, account_name, sheet_name, manual, clear_session):
    if clear_session:
        delete_session(account_name)

    creds = load_credentials(path, account_name, sheet_name)
    print(f"Account: {creds['name']}  (UID: {creds['uid']})")

    with sync_playwright() as p:
        context = make_context(p, account_name)

        if manual:
            page = manual_login(context, account_name)
        else:
            page, valid = restore_session(context, account_name)
            if not valid:
                print("\nRun with --manual to log in first:")
                print(f"  python3 login.py \"{path}\" --account \"{account_name}\" --manual")
                context.close()
                sys.exit(1)

        profile_url = f"https://www.facebook.com/{creds['uid']}"
        print(f"Opening profile: {profile_url}")
        page.goto(profile_url, wait_until="domcontentloaded")

        print("\nBrowser is open. Close it when done.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass

        context.close()


def main():
    parser = argparse.ArgumentParser(description="Open a Meta account from the spreadsheet.")
    parser.add_argument("file",            help="Path to the .xlsx workbook")
    parser.add_argument("--account",       required=True, help="Account name (e.g. NOS_PAN_001)")
    parser.add_argument("--sheet",         default="New VProfiles for BFL", help="Sheet name")
    parser.add_argument("--manual",        action="store_true", help="Log in manually (required first time or after session expires)")
    parser.add_argument("--clear-session", action="store_true", help="Delete saved session before starting")
    args = parser.parse_args()

    open_account(args.file, args.account, args.sheet, args.manual, args.clear_session)


if __name__ == "__main__":
    main()
