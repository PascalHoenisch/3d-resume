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
    import urllib.request

    def ensure_vendor_assets():
        os.makedirs(os.path.join('assets','js','vendor'), exist_ok=True)
        os.makedirs(os.path.join('assets','css','vendor'), exist_ok=True)
        # Ensure local ESM exists; download pinned version if missing
        esm_path = os.path.join('assets','js','vendor','three-cad-viewer.esm.js')
        if not os.path.exists(esm_path):
            try:
                url = 'https://unpkg.com/three-cad-viewer@3.5.1/dist/three-cad-viewer.esm.js'
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read()
                with open(esm_path, 'wb') as outf:
                    outf.write(data)
                print('[BUILD] Downloaded vendor ESM three-cad-viewer.esm.js (3.5.1)')
            except Exception as e:
                print(f"[BUILD] Warning: Could not download three-cad-viewer.esm.js: {e}")
        # Ensure CSS exists under assets/css/vendor; copy from old path if present, else download
        vendor_css_path = os.path.join('assets','css','vendor','three-cad-viewer.css')
        try:
            needs_upstream = False
            if os.path.exists(vendor_css_path):
                # If this file is our minimal placeholder (detected by header marker), replace with upstream CSS
                try:
                    with open(vendor_css_path, 'r', encoding='utf-8', errors='ignore') as fcss:
                        head = fcss.read(256)
                    if 'Lightweight, compatibility-safe stylesheet' in head:
                        needs_upstream = True
                except Exception:
                    # If we cannot read, attempt to refresh from upstream
                    needs_upstream = True
            else:
                # File missing; we need to provision it
                needs_upstream = True

            if needs_upstream:
                # Try to download official upstream CSS; if that fails, try to copy legacy file
                try:
                    url = 'https://unpkg.com/three-cad-viewer@3.5.1/dist/three-cad-viewer.css'
                    with urllib.request.urlopen(url, timeout=15) as resp:
                        data = resp.read()
                    os.makedirs(os.path.dirname(vendor_css_path), exist_ok=True)
                    with open(vendor_css_path, 'wb') as outf:
                        outf.write(data)
                    print('[BUILD] Ensured upstream vendor CSS three-cad-viewer.css (3.5.1)')
                except Exception as e_dl:
                    # Fallback: copy from legacy path if available
                    legacy_css_path = os.path.join('assets','css','three-cad-viewer.css')
                    if os.path.exists(legacy_css_path):
                        with open(legacy_css_path, 'rb') as src, open(vendor_css_path, 'wb') as dst:
                            dst.write(src.read())
                        print('[BUILD] Copied legacy CSS to assets/css/vendor/three-cad-viewer.css (download failed)')
                    else:
                        print(f"[BUILD] Warning: Could not ensure vendor CSS: {e_dl}")
        except Exception as e:
            print(f"[BUILD] Warning: Could not ensure vendor CSS: {e}")

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

    def remove_section(h: str, sec_id: str) -> str:
        """Remove the entire <section id="sec_id" ...> ... </section> block if present."""
        import re
        # non-greedy to match the nearest closing </section>
        pattern = re.compile(rf'<section[^>]*id="{re.escape(sec_id)}"[^>]*>.*?</section>', re.S | re.I)
        return pattern.sub('', h, count=1)

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

    # Ensure vendor assets are present (download if missing)
    ensure_vendor_assets()

    # If we have resume data, render into HTML
    if resume:
        basics = resume.get("basics", {})
        # Title
        name = basics.get("name") or ""
        label = basics.get("label") or ""
        title_text = (name + (" — " + label if label else "")) or "Lebenslauf"
        # Replace <title> ... </title>
        import re
        html = re.sub(r"<title>.*?</title>", f"<title>{esc(title_text)}</title>", html, flags=re.S)

        # --- SEO meta: description, canonical, OpenGraph/Twitter, theme-color, JSON-LD ---
        # Derive summary for description (truncate around 160 chars)
        raw_summary = str(basics.get("summary", "") or "").strip()
        desc = raw_summary
        if len(desc) > 160:
            # try to cut on word boundary
            cut = desc[:157]
            last_space = cut.rfind(" ")
            desc = (cut[:last_space] if last_space > 60 else cut) + "…"
        # Canonical: prefer provided website if present, else point to local index
        website = str(basics.get("website", "") or "").strip()
        canonical_href = website if website else "/index.html"
        # Avatar/image
        # avatar_src will be computed shortly below (local override). For SEO block, we temporarily use basics.image;
        # we'll replace it with the final avatar_src after it's known.
        og_image = (basics.get("image") or "")
        # Build social profile URLs for sameAs
        profiles = basics.get("profiles", []) or []
        same_as = [p.get("url") for p in profiles if isinstance(p, dict) and p.get("url")]
        # Email
        email = basics.get("email") or ""
        # Location
        city = (basics.get("location", {}) or {}).get("city") or ""
        country = (basics.get("location", {}) or {}).get("countryCode") or ""
        # Theme-color for light and dark
        theme_color_block = (
            '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#ffffff" />\n'
            '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0f1115" />'
        )
        # Open Graph and Twitter metas (image filled later if local avatar is found)
        seo_head = (
            f'\n  <meta name="description" content="{esc(desc)}" />\n'
            f'  <link rel="canonical" href="{esc(canonical_href)}" />\n'
            f'  <meta property="og:title" content="{esc(title_text)}" />\n'
            f'  <meta property="og:description" content="{esc(desc)}" />\n'
            f'  <meta property="og:type" content="profile" />\n'
            f'  <meta property="og:locale" content="de_DE" />\n'
            f'  <meta name="twitter:card" content="summary_large_image" />\n'
            f'  <meta name="twitter:title" content="{esc(title_text)}" />\n'
            f'  <meta name="twitter:description" content="{esc(desc)}" />\n'
            f'  {theme_color_block}\n'
        )
        # Insert placeholder for og:image/twitter:image to be patched later once avatar_src is computed
        seo_head += '  <!--__SEO_IMAGE_PLACEHOLDER__-->'
        # JSON-LD Person schema (image patched later)
        import json as _json
        person_ld = {
            "@context": "https://schema.org",
            "@type": "Person",
            "name": name,
            "jobTitle": label,
            "description": raw_summary or None,
            "email": f"mailto:{email}" if email else None,
            "image": "__SEO_IMAGE_JSONLD__",
            "url": website or None,
            "address": {
                "@type": "PostalAddress",
                "addressLocality": city or None,
                "addressCountry": country or None,
            },
            "sameAs": same_as or None,
        }
        # Remove None values cleanly
        def _drop_none(obj):
            if isinstance(obj, dict):
                return {k: _drop_none(v) for k, v in obj.items() if v is not None}
            if isinstance(obj, list):
                return [
                    _drop_none(v) for v in obj if v is not None
                ]
            return obj
        person_ld = _drop_none(person_ld)
        ld_json = _json.dumps(person_ld, ensure_ascii=False)
        seo_head += f"\n  <script type=\"application/ld+json\">{ld_json}</script>\n"
        # Inject all SEO tags before closing head for now (image URLs will be corrected below)
        html = re.sub(r"</head>", seo_head + "\n</head>", html, count=1)

        # Theme: add data-theme attribute to <body> based on resume.meta.theme (default: classic)
        meta = resume.get("meta", {}) if isinstance(resume.get("meta", {}), dict) else {}
        theme = str(meta.get("theme", "classic")).strip().lower() or "classic"
        # sanitize: allow only simple token characters
        import re as _re
        theme = _re.sub(r"[^a-z0-9_-]", "", theme)
        # Inject data-theme into the first <body> tag
        def _body_attr_inject(m):
            tag_open = m.group(0)
            if "data-theme=" in tag_open:
                return tag_open
            # insert before closing '>' while preserving any existing attributes
            if tag_open.endswith('>'):
                return tag_open[:-1] + f' data-theme="{esc(theme)}">'
            return tag_open
        html = _re.sub(r"<body(?![^>]*data-theme)[^>]*>", _body_attr_inject, html, count=1)

        # Basics fields
        # avatar src: prefer local /assets/image/person.* if present, prioritizing AVIF/WEBP over JPEG/PNG; fallback to basics.image
        local_avatar = None
        try:
            img_dir = os.path.join("assets", "image")
            if os.path.isdir(img_dir):
                # pick preferred by extension
                prefs = ['.avif', '.webp', '.jpeg', '.jpg', '.png']
                candidates = [fn for fn in os.listdir(img_dir) if fn.lower().startswith('person.')]
                def _score(fn):
                    import os as _os
                    return prefs.index(_os.path.splitext(fn.lower())[1]) if _os.path.splitext(fn.lower())[1] in prefs else 999
                if candidates:
                    candidates.sort(key=_score)
                    local_avatar = "/assets/image/" + candidates[0]
        except Exception:
            local_avatar = None
        avatar_src = local_avatar or basics.get("image") or ""
        if avatar_src:
            # Preload hero image to improve LCP
            html = re.sub(r"</head>", f"  <link rel=\"preload\" as=\"image\" href=\"{esc(avatar_src)}\" />\n</head>", html, count=1)
            # Add attributes to avatar image for better performance/CLS
            html = re.sub(
                r'<img id="avatar"([^>]*)>',
                f'<img id="avatar"\\1 src="{esc(avatar_src)}" width="120" height="120" decoding="async" fetchpriority="high" loading="eager">',
                html
            )
            # Patch SEO image placeholders now that avatar_src is known
            og_img_block = (
                f'  <meta property="og:image" content="{esc(avatar_src)}" />\n'
                f'  <meta name="twitter:image" content="{esc(avatar_src)}" />\n'
            )
            html = html.replace('  <!--__SEO_IMAGE_PLACEHOLDER__-->', og_img_block)
            html = html.replace('__SEO_IMAGE_JSONLD__', avatar_src)
        else:
            # Remove placeholder if no image available
            html = html.replace('  <!--__SEO_IMAGE_PLACEHOLDER__-->', '')
            html = html.replace('__SEO_IMAGE_JSONLD__', '')
        # name/label/summary
        html = set_inner(html, "name", esc(name))
        html = set_inner(html, "label", esc(label))
        html = set_inner(html, "summary", esc(basics.get("summary", "")))
        # email
        email = basics.get("email") or ""
        # Replace entire email anchor to avoid duplicate href attributes
        html = re.sub(r'<a id="email"[^>]*>.*?</a>', f'<a id="email" href="mailto:{esc(email)}">{esc(email or "E-Mail")}</a>', html, flags=re.S)
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
        if skills and skills_html:
            html = set_inner(html, "skillsList", skills_html)
        else:
            html = remove_section(html, "skills")

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
                '<div class="mobile-rotate-hint" role="note" aria-live="polite">'
                '<span class="hint-icon" aria-hidden="true">📱↻</span>'
                '<span>Für eine bessere Ansicht bitte das Smartphone drehen (Querformat) oder einen Desktop‑Browser verwenden.</span>'
                '</div>'
                '<div class="viewer-wrap">'
                '<div class="viewer-canvas"></div>'
                '</div>'
                '</div>'
            )
        if work_items:
            html = set_inner(html, "workList", "".join(work_items))
        else:
            html = remove_section(html, "work")

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
        if edu and edu_html:
            html = set_inner(html, "educationList", edu_html)
        else:
            html = remove_section(html, "education")

        # Awards
        awards = resume.get("awards", [])
        awards_html = "".join([f'<li><strong>{esc(a.get("title",""))}</strong>{(" — " + esc(a.get("awarder",""))) if a.get("awarder") else ""}</li>' for a in awards])
        if awards and awards_html:
            html = set_inner(html, "awardsList", awards_html)
        else:
            html = remove_section(html, "awards")

        # References
        refs = resume.get("references", [])
        refs_html = "".join([
            '<blockquote class="ref">'
            f'<div>{esc(r.get("reference",""))}</div>'
            f'<div class="muted" style="margin-top:8px">— {esc(r.get("name",""))}</div>'
            '</blockquote>'
            for r in refs
        ])
        if refs and refs_html:
            html = set_inner(html, "referencesList", refs_html)
        else:
            html = remove_section(html, "references")

        # Interests
        interests = resume.get("interests", [])
        interests_html = "".join([f'<li>{esc(i.get("name",""))}</li>' for i in interests])
        if interests and interests_html:
            html = set_inner(html, "interestsList", interests_html)
        else:
            html = remove_section(html, "interests")


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
        # Regenerate if the source files are newer than the newest generated page
        try:
            newest_mtime = os.path.getmtime(newest)
            src_candidates = [TEMPLATE_FILE, "resume.json"]
            for src in src_candidates:
                if os.path.exists(src) and os.path.getmtime(src) > newest_mtime:
                    return generate_page_from_template()
        except Exception as e:
            print(f"[BUILD] Warning: Could not compare mtimes, regenerating. Reason: {e}")
            return generate_page_from_template()
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

    def _is_asset(self) -> bool:
        p = (self.path or "").split('?', 1)[0]
        return p.startswith('/assets/')

    def _is_compressible_path(self) -> bool:
        import os as _os
        p = (self.path or "").split('?', 1)[0]
        _, ext = _os.path.splitext(p)
        return ext.lower() in {'.html', '.htm', '.css', '.js', '.mjs', '.json', '.svg', ''}

    def end_headers(self):
        # Caching policy: strong caching for immutable assets; no-store for HTML/pages
        if self._is_asset():
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        # Vary for compression negotiation
        if self._is_compressible_path():
            self.send_header("Vary", "Accept-Encoding")
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
                requested = self.path

        # Try to serve compressible static files with on-the-fly compression
        try:
            import mimetypes, gzip, io, os as _os
            accept = self.headers.get('Accept-Encoding', '') or ''
            path_only = requested
            # Resolve local filesystem path safely
            fs_path = _os.path.abspath(_os.path.join(_os.getcwd(), path_only.lstrip('/')))
            root = _os.path.abspath(_os.getcwd())
            if fs_path.startswith(root) and _os.path.isfile(fs_path):
                _, ext = _os.path.splitext(fs_path)
                if ext.lower() in ('.html', '.htm', '.css', '.js', '.mjs', '.json', '.svg'):
                    with open(fs_path, 'rb') as f:
                        raw = f.read()
                    # Pick encoding
                    encoding = None
                    data = raw
                    try:
                        if 'br' in accept:
                            import brotli  # type: ignore
                            data = brotli.compress(raw)
                            encoding = 'br'
                        elif 'gzip' in accept:
                            buf = io.BytesIO()
                            with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=6) as gz:
                                gz.write(raw)
                            data = buf.getvalue()
                            encoding = 'gzip'
                    except Exception:
                        # fall back to uncompressed
                        encoding = None
                        data = raw
                    ctype = mimetypes.guess_type(fs_path)[0] or 'application/octet-stream'
                    self.send_response(200)
                    self.send_header('Content-Type', ctype)
                    if encoding:
                        self.send_header('Content-Encoding', encoding)
                        self.send_header('Vary', 'Accept-Encoding')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
        except Exception:
            # Fall back to default handler
            pass

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
