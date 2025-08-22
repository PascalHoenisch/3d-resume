#!/usr/bin/env python3
import argparse
import contextlib
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from typing import Optional

# A dev-friendly static server that:
# - Serves ESM JS correctly (application/javascript)
# - Serves .wasm for WebAssembly modules
# - Serves .step/.stp for CAD files
# - Disables caching to make iteration easy
# - Auto-opens the browser to /index.html

PAGES_DIR = "page"
TEMPLATE_FILE = "assets/html/template.html"  # SPA template; assets live under ./assets


def timestamp_name() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + ".html"


def generate_page_from_template() -> str:
    import json
    import html as html_lib

    def esc(s: str) -> str:
        return html_lib.escape(s, quote=True)

    def set_inner(h: str, elem_id: str, new_html: str) -> str:
        # Replace innerHTML of the element with given id using a simple regex
        import re
        pattern = re.compile(rf'(<'
                             rf'[^>]*id="{re.escape(elem_id)}"[^>]*>)'
                             rf'(.*?)'
                             rf'(</[^>]+>)', re.S)
        def repl(m):
            return m.group(1) + new_html + m.group(3)
        return pattern.sub(repl, h, count=1)

    os.makedirs(PAGES_DIR, exist_ok=True)
    if not os.path.exists(TEMPLATE_FILE):
        raise FileNotFoundError(f"Template {TEMPLATE_FILE} not found")
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    # Normalize asset paths so timestamped pages under /page can load them correctly
    html = html.replace('href="./assets/', 'href="/assets/').replace('src="./assets/', 'src="/assets/')

    # Load resume.json and keep raw string for inline script (tests rely on it)
    resume_json_str = None
    resume = {}
    try:
        with open("resume.json", "r", encoding="utf-8") as rf:
            resume_json_str = rf.read()
            resume = json.loads(resume_json_str)
    except Exception as e:
        print(f"[BUILD] Warning: Could not read or parse resume.json: {e}")

    # If we have resume data, render into HTML
    if resume:
        basics = resume.get("basics", {})
        # Title
        name = basics.get("name") or ""
        label = basics.get("label") or ""
        title_text = (name + (" — " + label if label else "")) or "Resume"
        # Replace <title> ... </title>
        import re
        html = re.sub(r"<title>.*?</title>", f"<title>{esc(title_text)}</title>", html, flags=re.S)

        # Basics fields
        # avatar src: prefer local /assets/image/person.* if present, otherwise fall back to basics.image
        local_avatar = None
        try:
            img_dir = os.path.join("assets", "image")
            if os.path.isdir(img_dir):
                for fn in os.listdir(img_dir):
                    if fn.lower().startswith("person."):
                        local_avatar = "/assets/image/" + fn
                        break
        except Exception:
            local_avatar = None
        avatar_src = local_avatar or basics.get("image") or ""
        if avatar_src:
            html = re.sub(r'<img id="avatar"([^>]*)>', f'<img id="avatar"\\1 src="{esc(avatar_src)}">', html)
        # name/label/summary
        html = set_inner(html, "name", esc(name))
        html = set_inner(html, "label", esc(label))
        html = set_inner(html, "summary", esc(basics.get("summary", "")))
        # website link
        website = basics.get("website") or "#"
        website_text = re.sub(r'^https?://', '', website)
        html = re.sub(r'<a id="website"([^>]*)>', f'<a id="website"\\1 href="{esc(website)}">{esc(website_text)}', html)
        # email
        email = basics.get("email") or ""
        html = re.sub(r'<a id="email"([^>]*)>', f'<a id="email"\\1 href="mailto:{esc(email)}">{esc(email or "Email")}', html)
        # location
        loc_text = ", ".join([x for x in [basics.get("location", {}).get("city"), basics.get("location", {}).get("countryCode")] if x])
        html = set_inner(html, "location", esc(loc_text))
        # profiles
        profiles = basics.get("profiles", [])
        prof_html = "".join([
            f'<a href="{esc(p.get("url","#"))}" target="_blank" rel="noopener">{esc((p.get("network")+": ") if p.get("network") else "") + esc(p.get("username") or p.get("url") or "")}</a>'
        for p in profiles])
        html = set_inner(html, "profiles", prof_html)

        # Skills
        skills = resume.get("skills", [])
        skills_html = "".join([
            '<div class="card">'
            f'<strong>{esc(s.get("name",""))} • {esc(s.get("level",""))}</strong>'
            '<div class="badges" style="margin-top:8px">'
            + "".join([f'<span class="badge">{esc(k)}</span>' for k in (s.get("keywords") or [])]) +
            '</div>'
            '</div>'
            for s in skills
        ])
        html = set_inner(html, "skillsList", skills_html)

        # Work (with viewer containers)
        def fmt_date(d):
            return d or ""
        work = resume.get("work", [])
        work_items = []
        for idx, w in enumerate(work):
            step_url = w.get("stepUrl", "")
            json_url = w.get("jsonUrl", "")
            # Normalize relative URLs to be project-root relative so that pages under /page can load assets
            if isinstance(step_url, str) and step_url.startswith("./"):
                step_url = "/" + step_url[2:]
            if isinstance(json_url, str) and json_url.startswith("./"):
                json_url = "/" + json_url[2:]
            dates = f"{fmt_date(w.get('startDate',''))}{' — ' + fmt_date(w.get('endDate')) if w.get('endDate') else ''}"
            highlights = "".join([f'<span class="badge">{esc(h)}</span>' for h in (w.get("highlights") or [])[:5]])
            website = w.get("website") or ""
            website_link = f'<a href="{esc(website)}" target="_blank" rel="noopener">{esc(re.sub(r"^https?://", "", website))}</a>' if website else ''
            file_id = f"file-{idx}"
            work_items.append(
                '<div class="work-card" '
                + (f'data-json-url="{esc(json_url)}" ' if json_url else '')
                + (f'data-step-url="{esc(step_url)}" ' if step_url else '')
                + '>'
                '<div class="work-head">'
                '<div class="work-title">'
                f'<strong>{esc(w.get("name",""))} — {esc(w.get("position") or "")}</strong>'
                f'{website_link}'
                f'<span class="muted">{esc(dates)}</span>'
                '</div>'
                f'<div class="badges">{highlights}</div>'
                '</div>'
                f'<div>{esc(w.get("summary",""))}</div>'
                '<div class="viewer-wrap">'
                '<div class="viewer-canvas"></div>'
                '</div>'
                '</div>'
            )
        html = set_inner(html, "workList", "".join(work_items))

        # Education
        edu = resume.get("education", [])
        edu_html = "".join([
            '<div class="card">'
            f'<strong>{esc(e.get("institution",""))}</strong>'
            f'<div class="muted">{esc((e.get("studyType") or "") + (" — " + e.get("area") if e.get("area") else ""))}</div>'
            f'<div class="muted">{esc(((e.get("startDate") or "") + (" — " + e.get("endDate") if e.get("endDate") else "")))}</div>'
            '</div>'
            for e in edu
        ])
        html = set_inner(html, "educationList", edu_html)

        # Awards
        awards = resume.get("awards", [])
        awards_html = "".join([f'<li><strong>{esc(a.get("title",""))}</strong>{(" — " + esc(a.get("awarder",""))) if a.get("awarder") else ""}</li>' for a in awards])
        html = set_inner(html, "awardsList", awards_html)

        # References
        refs = resume.get("references", [])
        refs_html = "".join([
            '<blockquote class="ref">'
            f'<div>{esc(r.get("reference",""))}</div>'
            f'<div class="muted" style="margin-top:8px">— {esc(r.get("name",""))}</div>'
            '</blockquote>'
            for r in refs
        ])
        html = set_inner(html, "referencesList", refs_html)

        # Interests
        interests = resume.get("interests", [])
        interests_html = "".join([f'<li>{esc(i.get("name",""))}</li>' for i in interests])
        html = set_inner(html, "interestsList", interests_html)


    out_name = timestamp_name()
    out_path = os.path.join(PAGES_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[BUILD] Generated page: {out_path}")
    return out_path


def find_newest_page() -> Optional[str]:
    if not os.path.isdir(PAGES_DIR):
        return None
    candidates = [
        os.path.join(PAGES_DIR, fn)
        for fn in os.listdir(PAGES_DIR)
        if fn.lower().endswith(".html") and os.path.isfile(os.path.join(PAGES_DIR, fn))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def ensure_page_exists(force: bool = False) -> str:
    os.makedirs(PAGES_DIR, exist_ok=True)
    if force:
        return generate_page_from_template()
    newest = find_newest_page()
    if newest:
        # Regenerate only if the newest page appears to have broken relative asset paths
        try:
            with open(newest, "r", encoding="utf-8") as f:
                content = f.read()
            if ('href="./assets/' in content) or ('src="./assets/' in content):
                return generate_page_from_template()
        except Exception as e:
            print(f"[BUILD] Warning: Could not verify newest page, regenerating. Reason: {e}")
            return generate_page_from_template()
        return newest
    return generate_page_from_template()


class DevHandler(SimpleHTTPRequestHandler):
    # Extend MIME map for common modern types
    extensions_map = {
        **getattr(SimpleHTTPRequestHandler, "extensions_map", {}),
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".json": "application/json",
        ".wasm": "application/wasm",
        ".step": "model/step",
        ".stp": "model/step",
        "": "application/octet-stream",
    }


    def end_headers(self):
        # Disable cache to make local development easier
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        # Basic CORS for local testing (same-origin is fine, but this helps when embedding assets)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Friendlier console logs
        sys.stdout.write("[HTTP] " + (fmt % args) + "\n")

    def do_OPTIONS(self):
        # CORS preflight support
        self.send_response(204)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        # Special-case favicon to avoid 404 noise in logs
        requested = self.path.split('?', 1)[0]
        if requested == '/favicon.ico':
            # No favicon provided; return 204 No Content
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return


        # Route '/' or '/index.html' to newest page file under /page
        if requested in ('/', '/index.html'):
            newest = find_newest_page()
            if newest is None:
                # Attempt to ensure at least one page exists, then re-evaluate
                ensure_page_exists()
                newest = find_newest_page()
            if newest:
                self.path = f"/page/{os.path.basename(newest)}"
        return super().do_GET()

    def do_POST(self):
        return super().do_POST()


def find_free_port(preferred: int) -> int:
    if preferred:
        return preferred
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def open_browser_later(url: str, delay: float = 0.8):
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def run_server(directory: str, host: str, port: int):
    os.chdir(directory)
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, DevHandler)
    where = f"http://{host if host not in ('0.0.0.0', '') else 'localhost'}:{port}/index.html"
    print(f"\nServing SPA from: {os.path.abspath(directory)}")
    print(f"URL: {where}")
    print("Press Ctrl+C to stop.\n")
    open_browser_later(where)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="Serve the resume SPA locally.")
    parser.add_argument("-d", "--dir", default=".", help="Directory to serve (default: current directory)")
    parser.add_argument("-H", "--host", default="127.0.0.1", help="Host/IP to bind (default: 127.0.0.1)")
    parser.add_argument("-p", "--port", type=int, default=0, help="Port to bind (default: auto-pick)")
    args = parser.parse_args()

    # Ensure a timestamped page exists in /page before starting
    try:
        ensure_page_exists()
    except Exception as e:
        print(f"[BUILD] Failed to ensure page exists: {e}")

    port = find_free_port(args.port)
    run_server(args.dir, args.host, port)


if __name__ == "__main__":
    main()
