import json
import os
import re
import socket
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import unittest

import os, sys
sys.path.insert(0, os.getcwd())
import main


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port or main.find_free_port(0)
        self.httpd = None
        self.thread = None

    def start(self):
        # Use current repo root as serving dir
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


def url_open(url: str, timeout: float = 2.0):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)


def wait_for_ok(url: str, timeout: float = 5.0):
    start = time.time()
    last_exc = None
    while time.time() - start < timeout:
        try:
            resp = url_open(url, timeout=1.0)
            if 200 <= resp.status < 300:
                return resp  # caller is responsible for closing (used as context manager in tests)
            resp.close()
        except Exception as e:
            last_exc = e
        time.sleep(0.05)
    if last_exc:
        raise last_exc
    raise TimeoutError(f"Timed out waiting for {url}")


class IntegrationServerTest(unittest.TestCase):
    def setUp(self):
        # Backup resume.json
        self.resume_path = os.path.join(os.getcwd(), "resume.json")
        self._original_resume = None
        if os.path.exists(self.resume_path):
            with open(self.resume_path, "r", encoding="utf-8") as f:
                self._original_resume = f.read()

    def tearDown(self):
        # Restore resume.json
        if self._original_resume is not None:
            with open(self.resume_path, "w", encoding="utf-8") as f:
                f.write(self._original_resume)

    def test_server_serves_rendered_resume_and_assets(self):
        # Prepare a sample resume.json
        sample = {
            "meta": {"theme": "elegant"},
            "basics": {
                "name": "Jane Doe",
                "label": "Mechanical Engineer",
                "email": "jane@example.com",
                "website": "https://example.com",
                "location": {"city": "Berlin", "countryCode": "DE"},
                "profiles": [{"network": "github", "username": "janedoe", "url": "https://github.com/janedoe"}],
            },
            "work": [
                {"name": "Sample STP", "position": "CAD", "startDate": "2025-01-01", "stepUrl": "./3d-sources/step/Spannvorrichtung.STEP", "highlights": ["STP"]}
            ],
            "skills": [{"name": "CAD", "level": "Senior", "keywords": ["STEP", "OpenCascade"]}],
            "education": [],
            "awards": [],
            "references": [],
            "interests": []
        }
        with open(self.resume_path, "w", encoding="utf-8") as f:
            json.dump(sample, f)

        # Remove any previously generated pages to force regeneration for this sample
        pages_dir = os.path.join(os.getcwd(), 'page')
        if os.path.isdir(pages_dir):
            for fn in os.listdir(pages_dir):
                if fn.lower().endswith('.html'):
                    try:
                        os.remove(os.path.join(pages_dir, fn))
                    except Exception:
                        pass
        # Ensure a timestamped page exists (freshly generated from current resume.json)
        generated = main.ensure_page_exists(force=True)
        self.assertTrue(os.path.exists(generated))

        # Start the server
        srv = Server()
        try:
            srv.start()

            # Wait for index to be available and read HTML
            with wait_for_ok(f"{srv.base}/index.html", timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Assert that server-rendered HTML contains expected basics
            self.assertIn("Jane Doe", html)
            self.assertIn("Mechanical Engineer", html)
            # Email mailto link and website text should be present
            self.assertIn("mailto:jane@example.com", html)
            self.assertIn("example.com", html)
            # Local avatar should be used if present under /assets/image/person.*
            self.assertIn("/assets/image/person", html)

            # Assets JS should be served
            with wait_for_ok(f"{srv.base}/assets/js/app.js", timeout=5) as resp2:
                self.assertEqual(resp2.status, 200)
                js_head = resp2.read(32)
                self.assertTrue(len(js_head) > 0)

            # Favicon should respond with 204 (No Content)
            with url_open(f"{srv.base}/favicon.ico", timeout=2) as fav:
                self.assertEqual(fav.status, 204)
                cl = fav.headers.get("Content-Length")
                self.assertEqual(cl, "0")

            # The local avatar file should be served (if present)
            with wait_for_ok(f"{srv.base}/assets/image/person.png", timeout=5) as resp_img:
                self.assertEqual(resp_img.status, 200)

        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
