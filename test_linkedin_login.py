"""Quick test for LinkedIn login + session persistence."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import os, time

load_dotenv()

EMAIL    = os.getenv("LINKEDIN_EMAIL")
PASSWORD = os.getenv("LINKEDIN_PASSWORD")
SESSION  = Path("data/linkedin_session.json")

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            storage_state=str(SESSION) if SESSION.exists() else None,
        )
        page = context.new_page()

        # --- Try restoring saved session first ---
        if SESSION.exists():
            print("Session file found - checking if still valid...")
            page.goto("https://www.linkedin.com/feed", timeout=20000)
            time.sleep(3)
            if "/feed" in page.url or "/in/" in page.url:
                print(f"Session restored - at: {page.url}")
                page.close(); context.close(); browser.close()
                return
            else:
                print(f"Session expired - re-logging in...")

        # --- Fresh login ---
        print(f"Logging in as {EMAIL} ...")
        page.goto("https://www.linkedin.com/login", timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)

        # Use coordinates to click + type (avoids selector ambiguity)
        page.mouse.click(632, 440)   # email field center (from inspection: x=480+152, y=414+26)
        time.sleep(0.3)
        page.keyboard.type(EMAIL, delay=50)
        time.sleep(0.3)

        page.mouse.click(632, 516)   # password field center (x=480+152, y=490+26)
        time.sleep(0.3)
        page.keyboard.type(PASSWORD, delay=50)
        time.sleep(0.5)

        # Inspect buttons to find Sign In button coordinates
        buttons = page.evaluate("""
            () => Array.from(document.querySelectorAll('button')).map(el => ({
                text: el.innerText.trim(),
                type: el.type,
                visible: el.offsetParent !== null,
                rect: el.getBoundingClientRect()
            })).filter(b => b.visible)
        """)
        print("Visible buttons:")
        for b in buttons:
            print(f"  {b['text']!r} type={b['type']} rect={{x:{b['rect']['x']:.0f}, y:{b['rect']['y']:.0f}, w:{b['rect']['width']:.0f}, h:{b['rect']['height']:.0f}}}")

        # Click Sign In button by coordinates
        sign_in_btn = next((b for b in buttons if b["text"].strip().lower() == "sign in"), None)
        if sign_in_btn:
            cx = sign_in_btn["rect"]["x"] + sign_in_btn["rect"]["width"] / 2
            cy = sign_in_btn["rect"]["y"] + sign_in_btn["rect"]["height"] / 2
            print(f"Clicking Sign In button at ({cx:.0f}, {cy:.0f})")
            page.mouse.click(cx, cy)
        else:
            print("Sign In button not found - trying Enter key")
            page.keyboard.press("Enter")
        time.sleep(5)

        print(f"Post-login URL: {page.url}")

        # Detect all verification screens (checkpoint URL, app notification, OTP, CAPTCHA)
        page_text = page.inner_text("body")
        needs_verification = (
            "checkpoint" in page.url
            or "challenge" in page.url
            or "Check your LinkedIn app" in page_text
            or "verification" in page_text.lower()
            or "security check" in page_text.lower()
            or "Enter the OTP" in page_text
        )

        if needs_verification:
            print("\nLinkedIn requires verification.")
            print("-> Approve it on your LinkedIn mobile app now.")
            print("-> Waiting up to 60 seconds for approval...")
            page.wait_for_url("**/feed**", timeout=60000)

        if "/feed" in page.url or "/in/" in page.url:
            context.storage_state(path=str(SESSION))
            print(f"Login successful - session saved to {SESSION}")
        else:
            page.screenshot(path="data/linkedin_debug_final.png")
            print(f"Login failed - final URL: {page.url} - see data/linkedin_debug_final.png")

        time.sleep(2)
        page.close()
        context.close()
        browser.close()

if __name__ == "__main__":
    test()
