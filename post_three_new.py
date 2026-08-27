import sys, os, random, re, time

sys.path.insert(0, '/Users/macemilia/Desktop/Scripts')

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from session_manager import load_session, save_session

ACCOUNT      = "100016043628196"
PROFILES_DIR = "/Users/macemilia/Desktop/Scripts/browser_profiles"
PAGE_URL     = "https://www.facebook.com/profile.php?id=61593163022127"
MIN_DELAY, MAX_DELAY = 45, 90

# Los tres posteos nuevos (el 1 lleva link, el 2 y el 3 son solo texto)
posts = [
    {
        "text": (
            "You don't need a five-year plan to be on the right path. "
            "You just need to be a little better than you were yesterday. \U0001F4C8\n"
            "Small steps, done consistently, beat big plans that never start.\n"
            "#CareerGrowth #SelfImprovement #KeepGoing"
        ),
        "url": "www.visioncompassdesk.com",
    },
    {
        "text": (
            "Ambition doesn't mean saying yes to everything. Sometimes the most "
            "productive thing you can do is protect your energy. \U0001F4BC\n"
            "Set the boundary. Do the work that matters. Rest without guilt.\n"
            "#WorkLifeBalance #CareerTips #ProtectYourPeace"
        ),
        "url": None,
    },
    {
        "text": (
            "The skill you're avoiding because you feel like a beginner? "
            "That's exactly the one worth learning. \U0001F331\n"
            "Growth lives outside the comfort zone.\n"
            "#SelfImprovement #LifelongLearning #LevelUp"
        ),
        "url": None,
    },
]


def human_type(page, text):
    for char in text:
        page.keyboard.type(char)
        time.sleep(random.uniform(0.05, 0.15))


def human_pause(a=0.8, b=2.0):
    time.sleep(random.uniform(a, b))


def is_logged_in(url):
    return (
        "facebook.com" in url
        and "/login" not in url
        and "login.php" not in url
    )


def publish_post(page, post, index):
    print(f"\n── Post {index + 1} {'[LINK]' if post['url'] else ''} ──", flush=True)

    # Navegacion fresca + scroll al tope en cada posteo
    page.goto(PAGE_URL, wait_until="domcontentloaded")
    human_pause(3.0, 4.5)
    page.evaluate("window.scrollTo(0, 0)")
    human_pause(1.0, 2.0)

    print("Opening composer...", flush=True)
    clicked = False
    for selector in [
        "div[role='main'] div[aria-label=\"What's on your mind?\"]",
        "div[role='main'] div[role='button']:has-text(\"What's on your mind?\")",
        "div[role='main'] span:has-text(\"What's on your mind?\")",
    ]:
        try:
            el = page.locator(selector).first
            if el.is_visible():
                el.scroll_into_view_if_needed()
                el.click()
                human_pause(2.0, 3.0)
                clicked = True
                print(f"  Clicked: {selector}", flush=True)
                break
        except Exception:
            continue

    if not clicked:
        page.screenshot(path=f"/Users/macemilia/Desktop/Scripts/debug_post{index + 1}.png")
        print(f"  Could not find composer -- screenshot saved to debug_post{index + 1}.png", flush=True)
        return False

    print("Waiting for composer dialog...", flush=True)
    try:
        page.wait_for_selector("div[role='dialog']", timeout=8000)
        human_pause(1.0, 2.0)
    except Exception:
        print("  Dialog did not appear -- trying to type directly", flush=True)

    print("Typing content...", flush=True)
    try:
        textbox = page.locator("div[role='dialog'] div[role='textbox'][contenteditable='true']").first
        if textbox.count() > 0:
            textbox.click()
            human_pause(0.5, 1.0)
        else:
            page.locator("div[role='textbox'][contenteditable='true']").last.click()
            human_pause(0.5, 1.0)
    except Exception:
        pass

    human_type(page, post["text"])

    if post["url"]:
        human_pause(0.5, 1.2)
        print(f"Adding URL: {post['url']}", flush=True)
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        human_type(page, post["url"])
        print("Waiting for link preview...", flush=True)
        human_pause(5.0, 7.0)

    human_pause(1.0, 2.0)

    # Dismiss hashtag/mention autocomplete by clicking dialog header (safe — won't close dialog)
    try:
        autocomplete = page.locator("div[role='dialog'] ul[role='listbox'], div[role='dialog'] div[role='listbox']")
        if autocomplete.count() > 0 and autocomplete.first.is_visible():
            print("  Dismissing autocomplete...", flush=True)
            header = page.locator("div[role='dialog'] h2").first
            if header.is_visible():
                header.click()
            else:
                page.locator("div[role='dialog']").first.click(position={"x": 10, "y": 10})
            human_pause(0.5, 0.8)
    except Exception:
        pass

    page.screenshot(path=f"/Users/macemilia/Desktop/Scripts/debug_submit{index + 1}.png")
    print(f"  Screenshot saved: debug_submit{index + 1}.png", flush=True)

    print("Submitting...", flush=True)
    submitted = False
    for s in [
        "div[role='dialog'] div[aria-label='Next'][role='button']",
        "div[role='dialog'] div[aria-label='Post'][role='button']",
        "div[role='dialog'] div[role='button']:has-text('Next')",
        "div[role='dialog'] div[role='button']:has-text('Post')",
    ]:
        try:
            el = page.locator(s).last
            if el.count() > 0 and el.is_visible():
                el.click()
                submitted = True
                print(f"  Submitted via: {s}", flush=True)
                break
        except Exception:
            continue

    if not submitted:
        try:
            for name in [r"^Next$", r"^Post$"]:
                btn = page.locator("div[role='dialog']").get_by_role(
                    "button", name=re.compile(name, re.I)
                ).last
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    submitted = True
                    print(f"  Submitted via role button '{name}'", flush=True)
                    break
        except Exception:
            pass

    if not submitted:
        print(f"  Post button not found -- please click Post manually.", flush=True)
        human_pause(20.0, 20.0)
        return False

    page.wait_for_load_state("domcontentloaded")
    human_pause(2.5, 4.0)
    print(f"Post {index + 1} published.", flush=True)
    return True


# --- Main ---------------------------------------------------------------
user_data_dir = os.path.join(PROFILES_DIR, ACCOUNT)
cookies = load_session(ACCOUNT)
if not cookies:
    print("No saved session found.", flush=True)
    sys.exit(1)

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

    print("Loading session and navigating to page...", flush=True)
    context.add_cookies(cookies)
    page.goto(PAGE_URL, wait_until="domcontentloaded")
    human_pause(2.5, 4.0)
    print(f"URL: {page.url}", flush=True)

    if not is_logged_in(page.url):
        print("La sesion guardada parece vencida -- volve a loguearte y guardar sesion antes de correr este script.", flush=True)
        context.close()
        sys.exit(1)

    # Por si la pagina todavia no quedo "cambiada" a la identidad de Page
    try:
        switch_btn = page.get_by_role("button", name=re.compile(r"switch now", re.I))
        if switch_btn.count() > 0:
            print("Clicking 'Switch Now'...", flush=True)
            switch_btn.click()
            page.wait_for_load_state("domcontentloaded")
            human_pause(2.5, 4.0)
            print("Switched to page successfully.", flush=True)
    except Exception as e:
        print(f"Switch Now not found or already on page: {e}", flush=True)

    print("\nStarting posts...\n", flush=True)
    for i, post in enumerate(posts):
        publish_post(page, post, i)
        if i < len(posts) - 1:
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            print(f"\nWaiting {delay}s before next post...", flush=True)
            time.sleep(delay)

    save_session(ACCOUNT, context.cookies())
    print("\nAll done. Session saved.", flush=True)
    print("Close the browser when finished.", flush=True)
    try:
        page.wait_for_event("close", timeout=0)
    except Exception:
        pass
    context.close()
