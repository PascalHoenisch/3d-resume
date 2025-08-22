import threading
import unittest
from http.server import ThreadingHTTPServer

import os, sys
sys.path.insert(0, os.getcwd())
import main

try:
    from playwright.sync_api import sync_playwright  # type: ignore
    HAVE_PLAYWRIGHT = True
except Exception:
    HAVE_PLAYWRIGHT = False


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port or main.find_free_port(0)
        self.httpd = None
        self.thread = None

    def start(self):
        server_address = (self.host, self.port)
        self.httpd = ThreadingHTTPServer(server_address, main.DevHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=2)

    @property
    def base(self):
        return f"http://{self.host}:{self.port}"


class BrowserEmulationTest(unittest.TestCase):
    @unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright not installed")
    def test_browser_has_no_errors_and_viewer_mounts_canvas(self):
        # Ensure a fresh page exists
        main.ensure_page_exists(force=True)
        srv = Server()
        try:
            srv.start()
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                console_entries = []
                page_errors = []

                def on_console(msg):
                    try:
                        console_entries.append({
                            "type": msg.type(),
                            "text": msg.text(),
                        })
                    except Exception:
                        pass

                def on_page_error(exc):
                    try:
                        page_errors.append(str(exc))
                    except Exception:
                        page_errors.append("<unserializable pageerror>")

                page.on("console", on_console)
                page.on("pageerror", on_page_error)

                page.goto(f"{srv.base}/index.html", wait_until="domcontentloaded")

                # Ensure work cards and viewer container exist
                self.assertIsNotNone(page.query_selector(".work-card"))
                self.assertIsNotNone(page.query_selector(".viewer-canvas"))

                # Wait for the viewer to mount some content into the container (child element appears)
                # Give enough time for WASM/module to load in CI
                page.wait_for_selector(".viewer-canvas *", timeout=15000)

                # Try clicking Fit View if the button is present
                btn = page.query_selector("button[data-action='fit']")
                if btn:
                    btn.click()

                # Evaluate console health
                # Fail on any pageerror
                self.assertEqual(page_errors, [], f"Page errors occurred: {page_errors}")

                # Collect console errors
                error_texts = [e["text"] for e in console_entries if e.get("type") == "error"]
                self.assertEqual(error_texts, [], f"Console errors: {error_texts}")

                # Also fail if known failure warnings/messages appear
                red_flags = [
                    "Failed to construct CadViewer with both signatures",
                    "Viewer initialization failed (init/initialize)",
                    "Auto-load from URL failed",
                ]
                bad_warns = [e["text"] for e in console_entries if any(flag in e.get("text", "") for flag in red_flags)]
                self.assertEqual(bad_warns, [], f"Viewer warnings indicate failure: {bad_warns}")

                browser.close()
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
