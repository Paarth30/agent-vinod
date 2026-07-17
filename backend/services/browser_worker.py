"""Owns a single headed Playwright browser/context for the lifetime of the
backend process. Playwright's sync API is not safe to use across threads, so
every Playwright call must run on this one dedicated thread — other threads
submit zero-arg callables (closing over `browser_worker.context`) and block
until the browser thread runs them."""
import threading
from pathlib import Path
from queue import Queue

from steps.browser_session import linkedin_login, browser_context_no_login

SESSION_FILE = Path("data/linkedin_session.json")


class BrowserWorker:
    def __init__(self):
        self._task_queue: Queue = Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="browser-worker")
        self.context = None
        self.started = False

    def start(self, timeout: float = 90.0):
        if self.started:
            return
        self.started = True
        self._thread.start()
        self._ready.wait(timeout=timeout)

    def _run(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            # no_viewport=True: this window gets handed to a human for manual-apply
            # fallback. Without it, Playwright locks the page to a fixed virtual
            # viewport (1280x720) via CDP regardless of the actual OS window size —
            # resizing/maximizing the window then leaves the real content clipped to
            # that fixed region with blank space around it, which looks like the
            # page "isn't loading."
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None,
                no_viewport=True,
            )
            try:
                linkedin_login(context, SESSION_FILE)
            except Exception:
                pass  # continue without a session — discovery will just show as logged out
            self.context = context
            self._ready.set()

            while True:
                item = self._task_queue.get()
                if item is None:
                    break
                fn, result_holder, done_event = item
                try:
                    result_holder["value"] = fn()
                except Exception as e:
                    result_holder["error"] = e
                finally:
                    done_event.set()

            context.close()
            browser.close()

    def submit(self, fn):
        """Run fn() on the browser thread, blocking the calling thread until done.
        Call this from a background worker thread, never from the asyncio event loop."""
        if not self.started:
            raise RuntimeError("BrowserWorker not started")
        result_holder: dict = {}
        done_event = threading.Event()
        self._task_queue.put((fn, result_holder, done_event))
        done_event.wait()
        if "error" in result_holder:
            raise result_holder["error"]
        return result_holder.get("value")

    def stop(self):
        if self.started:
            self._task_queue.put(None)


browser_worker = BrowserWorker()
