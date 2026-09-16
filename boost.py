"""
boost.py  —  Phase 2
Creates a Facebook engagement ad campaign for the most recent post on a page.
Run this after post.py has published posts.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"
POSTS_FILE = ROOT / "posts.txt"


# ── Credentials ───────────────────────────────────────────────────────────────

def _load_dotenv():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip()


def ensure_credentials():
    _load_dotenv()

    keys = ["MLX_EMAIL", "MLX_PASSWORD", "TEXTVERIFIED_API_KEY", "TEXTVERIFIED_USERNAME"]
    values = {k: os.environ.get(k, "").strip() for k in keys}

    if all(values.values()):
        return

    print("\n── Credentials ───────────────────────────────────────────")
    print("(Saved to .env so you only need to enter them once.)\n")

    if not values["MLX_EMAIL"]:
        values["MLX_EMAIL"] = input("  Multilogin email: ").strip()
    if not values["MLX_PASSWORD"]:
        values["MLX_PASSWORD"] = getpass.getpass("  Multilogin password: ").strip()
    if not values["TEXTVERIFIED_API_KEY"]:
        values["TEXTVERIFIED_API_KEY"] = input("  TextVerified API key: ").strip()
    if not values["TEXTVERIFIED_USERNAME"]:
        values["TEXTVERIFIED_USERNAME"] = input("  TextVerified username (email): ").strip()

    for k, v in values.items():
        os.environ[k] = v

    existing = []
    if ENV_FILE.exists():
        existing = [l for l in ENV_FILE.read_text().splitlines()
                    if not any(l.startswith(k) for k in keys)]
    lines = existing + [f"{k}={v}" for k, v in values.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    print("  Saved to .env")


# ── Account picker ────────────────────────────────────────────────────────────

def pick_account() -> str:
    from mlx_context import list_accounts
    accounts = list_accounts()

    print("\n── Accounts ──────────────────────────────────────────────")
    for i, name in enumerate(accounts, 1):
        print(f"  {i}. {name}")

    while True:
        choice = input(f"\n  Pick an account [1-{len(accounts)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(accounts):
            return accounts[int(choice) - 1]
        print("  Please enter a number from the list.")


def ask_publish_mode() -> bool:
    print("\n── Publish mode ──────────────────────────────────────────")
    choice = input(
        "  Publish now, or save as draft to review first?\n"
        "  [draft/publish] (default: draft): "
    ).strip().lower()
    return choice in ("publish", "p", "yes", "y")


# ── TextVerified SMS ──────────────────────────────────────────────────────────

def _get_sms_code(verification) -> str | None:
    from textverified import TextVerified
    tv = TextVerified(
        api_key=os.environ["TEXTVERIFIED_API_KEY"],
        api_username=os.environ["TEXTVERIFIED_USERNAME"],
    )
    print("  Waiting for SMS code (up to 2 minutes)...")
    for sms in tv.sms.incoming(data=verification, timeout=120.0):
        digits = "".join(filter(str.isdigit, sms.text or ""))
        if digits:
            return digits
    return None


async def _handle_verification(page) -> bool:
    """Reserve a TextVerified number, enter it in Facebook, receive and submit the code."""
    try:
        from textverified import TextVerified
        from textverified.models import ReservationCapability
    except ImportError:
        print("  textverified package not installed — run setup.bat first.")
        input("  Complete verification manually, then press Enter...")
        return True

    try:
        tv = TextVerified(
            api_key=os.environ["TEXTVERIFIED_API_KEY"],
            api_username=os.environ["TEXTVERIFIED_USERNAME"],
        )
        print("  Requesting US number from TextVerified...")
        verification = tv.verifications.create(
            service_name="Facebook",
            capability=ReservationCapability.SMS,
        )
        phone = verification.phone_number
        print(f"  Got number: {phone}")

        phone_input = await page.wait_for_selector(
            'input[type="tel"], input[placeholder*="phone"], input[placeholder*="number"]',
            timeout=10000,
        )
        await phone_input.fill(phone)
        await page.wait_for_timeout(500)

        for label in ["Send code", "Get code", "Send"]:
            try:
                await page.click(f'button:has-text("{label}")', timeout=3000)
                break
            except Exception:
                continue

        await page.wait_for_timeout(2000)

        # Poll for code in a thread so we don't block the event loop
        code = await asyncio.to_thread(_get_sms_code, verification)

        if code:
            print(f"  Received code: {code}")
            code_input = await page.wait_for_selector(
                'input[placeholder*="code"], input[type="number"], input[autocomplete="one-time-code"]',
                timeout=10000,
            )
            await code_input.fill(code)
            await page.wait_for_timeout(500)
            for label in ["Confirm", "Submit", "Continue"]:
                try:
                    await page.click(f'button:has-text("{label}")', timeout=3000)
                    break
                except Exception:
                    continue
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            tv.verifications.cancel(verification.id)
            return True
        else:
            print("  Could not receive SMS code automatically.")
            input("  Complete verification manually, then press Enter...")
            tv.verifications.cancel(verification.id)
            return True

    except Exception as exc:
        print(f"  Verification error: {exc}")
        input("  Complete verification manually, then press Enter...")
        return True


# ── Main ad creation flow ─────────────────────────────────────────────────────

async def boost(cdp_url: str, publish: bool = False):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # ── Navigate to Ads Manager ───────────────────────────────
        # Use window.location — page.goto() bypasses Multilogin's proxy-auth
        # injection and fails with ERR_INVALID_AUTH_CREDENTIALS.
        print("Opening Ads Manager...")
        await page.evaluate(
            "(u) => { window.location.href = u; }",
            "https://adsmanager.facebook.com/adsmanager/manage/campaigns",
        )
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        try:
            await page.wait_for_selector("text=Campaigns", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        # ── Create campaign ───────────────────────────────────────
        print("Creating campaign...")
        await page.wait_for_timeout(2000)

        # Target the green "+ Create" button precisely — avoid "Create a view" etc.
        clicked = False
        for selector in [
            '[data-testid="create-entity-button"]',
            'a[href*="create"]:has-text("Create"):not(:has-text("view"))',
            'div[aria-label="Create campaign"]',
        ]:
            try:
                await page.click(selector, timeout=4000)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            # Last resort: find the link/button whose full text is exactly "Create" or "+ Create"
            try:
                btn = page.locator('a, button, div[role="button"]').filter(
                    has_text=re.compile(r'^\+?\s*Create$', re.I)
                ).first
                await btn.click(timeout=8000)
                clicked = True
            except Exception:
                pass

        if not clicked:
            raise RuntimeError("Could not find the + Create campaign button in Ads Manager.")
        await page.wait_for_timeout(1500)

        # Wait for "Loading creation" spinner to fully disappear before interacting.
        # Use wait_for_function polling the DOM text directly — more reliable than
        # selector state on slow networks where the overlay can persist well past 20s.
        print("  Waiting for creation dialog to load...")
        try:
            await page.wait_for_function(
                "() => !document.body.innerText.includes('Loading creation')",
                timeout=90000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        # Screenshot here so we always know what state the page is in after + Create
        await page.screenshot(path=str(ROOT / "debug_after_create.png"))
        print("  Screenshot saved: debug_after_create.png")

        # If we landed directly on the campaign editor (Facebook remembers the last objective
        # and skips the picker), the "Next" button will already be present — skip ahead.
        already_on_editor = await page.get_by_role("button", name=re.compile(r"^Next$", re.I)).count() > 0

        if not already_on_editor:
            # Objective picker is showing — click Engagement then Continue
            engagement_clicked = False
            for locator in [
                page.get_by_text("Engagement", exact=True),
                page.locator('div[role="dialog"] :text("Engagement")'),
                page.locator(':text("Engagement")').filter(has_not_text="New").filter(has_not_text="Post"),
            ]:
                try:
                    await locator.first.click(timeout=6000)
                    engagement_clicked = True
                    break
                except Exception:
                    continue
            if not engagement_clicked:
                raise RuntimeError("Could not find Engagement objective — check debug_after_create.png")
            await page.wait_for_timeout(800)

            for locator in [
                page.locator('div[role="dialog"]').get_by_role("button", name=re.compile(r"^Continue$", re.I)),
                page.get_by_role("button", name=re.compile(r"^Continue$", re.I)),
            ]:
                try:
                    await locator.click(timeout=6000)
                    break
                except Exception:
                    continue
            await page.wait_for_timeout(1500)

        # Some accounts show a second "Manual vs Recommended" dialog
        try:
            await page.locator('div[role="dialog"] :text("Manual")').first.click(timeout=6000)
            await page.wait_for_timeout(800)
            await page.locator('div[role="dialog"]').get_by_role(
                "button", name=re.compile(r"^Continue$", re.I)
            ).click(timeout=6000)
            await page.wait_for_timeout(1200)
        except Exception:
            pass

        # Campaign editor page — click Next to reach the Ad Set section
        await page.get_by_role("button", name=re.compile(r"^Next$", re.I)).click(timeout=10000)
        await page.wait_for_timeout(1500)

        # ── Ad set ────────────────────────────────────────────────
        print("Configuring ad set...")
        # "On your ad" is an option inside the "Message destinations" dropdown
        await page.click("text=Message destinations", timeout=10000)
        await page.wait_for_timeout(600)
        await page.click('text="On your ad"', timeout=8000)
        await page.wait_for_timeout(1000)

        # Switch engagement type from default "Video views" to "Post engagement"
        try:
            await page.click("text=Video views", timeout=8000)
            await page.wait_for_timeout(600)
            await page.click("text=Post engagement", timeout=5000)
            await page.wait_for_timeout(800)
        except Exception:
            pass  # already set, or account defaults differently

        # Location targeting — scroll the inner form container (Ads Manager doesn't use window scroll)
        print("Setting location: Paraguay...")

        async def scroll_form(amount):
            await page.evaluate("""(amount) => {
                const candidates = [...document.querySelectorAll('div')]
                    .filter(el => el.scrollHeight > el.clientHeight + 50
                                  && getComputedStyle(el).overflowY !== 'visible'
                                  && getComputedStyle(el).overflowY !== 'hidden'
                                  && el.clientHeight > 200);
                const tallest = candidates.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
                if (tallest) tallest.scrollTop += amount;
            }""", amount)

        included = page.locator("text=Included location:").first
        for _ in range(40):
            if await included.count() > 0:
                visible = await included.is_visible()
                if visible:
                    break
            await scroll_form(200)
            await page.wait_for_timeout(200)

        inc_handle = await included.element_handle()
        await page.evaluate(
            "el => el.scrollIntoView({block: 'center', behavior: 'instant'})", inc_handle
        )
        await page.wait_for_timeout(1000)

        # Click the Edit link nearest to the Locations heading
        heading = page.locator("text=* Locations").first
        heading_box = await heading.bounding_box()
        anchor_box = heading_box or await included.bounding_box()

        async def nearest_edit():
            best, best_dy = None, None
            for c in await page.locator('text="Edit"').all():
                cbox = await c.bounding_box()
                if cbox and anchor_box and cbox["y"] >= anchor_box["y"] - 5:
                    dy = cbox["y"] - anchor_box["y"]
                    if best_dy is None or dy < best_dy:
                        best_dy, best = dy, c
            return best

        edit_btn = await nearest_edit()
        if edit_btn is None:
            await page.screenshot(path=str(ROOT / "debug_location.png"))
            raise RuntimeError("Could not find the Locations Edit link. Screenshot saved to debug_location.png")
        await edit_btn.click(timeout=8000)
        await page.wait_for_timeout(1000)

        # Find the country search input (label varies by account)
        search = None
        for sel in [
            'input[placeholder*="ountry" i]',
            'input[placeholder*="ocation" i]',
            'input[aria-label*="ocation" i]',
            'input[aria-label="Add locations"]',
        ]:
            try:
                cand = page.locator(sel).first
                if await cand.is_visible(timeout=2000):
                    search = cand
                    break
            except Exception:
                continue
        if not search:
            raise RuntimeError("No location search input found after clicking Edit.")

        await search.fill("Paraguay")
        await page.wait_for_timeout(1000)
        await search.press("Enter")
        await page.wait_for_timeout(1000)

        await page.get_by_role("button", name=re.compile(r"^Next$", re.I)).click(timeout=10000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass

        # ── Ad level: select existing post ────────────────────────
        link_url = None
        if POSTS_FILE.exists():
            match = re.search(r"https?://\S+", POSTS_FILE.read_text(encoding="utf-8"))
            if match:
                link_url = match.group()

        print(f"Selecting link post ({link_url or 'unknown URL'})...")
        use_existing = page.locator("text=Use existing post").first
        await use_existing.wait_for(state="attached", timeout=15000)
        for _ in range(20):
            if await use_existing.is_visible():
                break
            await scroll_form(200)
            await page.wait_for_timeout(200)
        await use_existing.click(timeout=10000)
        await page.wait_for_timeout(1000)
        await page.click("text=Select post")
        await page.wait_for_timeout(2000)

        # The post picker is a table sorted newest first.
        # Rows with numeric post IDs (15+ digits) are the selectable items.
        # If we have the link URL, prefer the row whose text contains the domain.
        await page.wait_for_timeout(2000)

        rows = page.locator("text=/^\\d{15,}$/")
        await rows.first.wait_for(state="visible", timeout=15000)

        chosen = None
        if link_url:
            domain = urlparse(link_url).netloc
            domain_rows = rows.filter(has_text=domain)
            if await domain_rows.count() > 0:
                chosen = domain_rows.first

        if chosen is None:
            chosen = rows.first

        await chosen.click(timeout=10000)
        await page.wait_for_timeout(1000)

        for label in ["Continue", "Select"]:
            try:
                await page.click(f'button:has-text("{label}")', timeout=4000)
                break
            except Exception:
                continue
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass

        # ── Publish or draft ──────────────────────────────────────
        if not publish:
            print("\nCampaign saved as draft. Review and publish it manually in Ads Manager → Drafts.")
            return

        print("Publishing campaign...")
        publish_clicked = False
        for locator in [
            page.get_by_role("button", name=re.compile(r"publish", re.I)),
            page.locator('button:has-text("Publish")'),
            page.locator('div[role="button"]:has-text("Publish")'),
        ]:
            try:
                await locator.first.click(timeout=10000)
                publish_clicked = True
                break
            except Exception:
                continue
        if not publish_clicked:
            raise RuntimeError("Could not find the Publish button.")
        await page.wait_for_timeout(3000)

        # ── SMS verification (if triggered) ───────────────────────
        needs_verification = False
        for text in ["Verifying your changes", "Enter confirmation code", "confirm your identity"]:
            try:
                el = await page.query_selector(f"text={text}")
                if el:
                    needs_verification = True
                    break
            except Exception:
                pass

        if needs_verification:
            print("\nSMS verification required...")
            await _handle_verification(page)

        await page.wait_for_timeout(2000)
        print("\nCampaign published successfully.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("=" * 54)
    print("   Facebook Ad Booster")
    print("=" * 54)

    ensure_credentials()
    account = pick_account()
    publish = ask_publish_mode()

    print(f"\nStarting profile '{account}'...")
    from mlx_context import start_profile_for
    client, started = start_profile_for(account)

    try:
        asyncio.run(boost(started.cdp_url, publish=publish))
    finally:
        client.stop_profile(started.profile_id)

    print("\n" + "=" * 54)
    print("   Done.")
    print("=" * 54)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
    except Exception as exc:
        print(f"\n\nError: {exc}")
    input("\nPress Enter to close...")
