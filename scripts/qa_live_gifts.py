#!/usr/bin/env python3
"""Read-only live-page browser QA for the gift certificate IndexResearch release."""
from __future__ import annotations
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

SLUG = "gift-certificates-cultural-learning-russia-2026"
BASE = "https://indexresearch.ru"
CANON = "https://github.com/IndexResearch-ru/" + SLUG
PAGES = [
    ("ru", f"{BASE}/{SLUG}.html", "ru", CANON),
    ("en", f"{BASE}/en/{SLUG}.html", "en", CANON + "-en"),
    ("cn", f"{BASE}/cn/{SLUG}.html", "zh-CN", CANON + "-cn"),
]
REFERRAL_HOST = "kpwfp.com"
REFERRAL_PATH = "/g/tgektb7aezd51c42ca8d81b5a96799/"
ERID = "2bL9aMPo2e49hMef4rrTsCbUmp"
VALID_LANDING = {
    "https://online.synchronize.ru/gifts",
    "https://online.synchronize.ru/art/guide",
}
OUTPUT = Path("qa_live_gifts_artifacts")
OUTPUT.mkdir(exist_ok=True)
failures = []
metrics = []
github_metrics = []


def record_fail(lang, width, kind, detail):
    failures.append({"lang": lang, "viewport": width, "kind": kind, "detail": str(detail)})


def validate(page, lang, width, expected_url, expected_lang, repo):
    # Lazy-loading images below the fold are valid, but not yet complete until
    # scrolled into view. Force their lazy load without clicking links.
    for img in page.locator("main img").all():
        try:
            img.scroll_into_view_if_needed(timeout=12000)
            img.evaluate("(el) => { el.loading = 'eager'; }")
            img.evaluate("(el) => el.decode().catch(() => null)")
        except Exception as exc:
            record_fail(lang, width, "image-load-probe", repr(exc))
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(200)
    js = """() => {
      const m = document.querySelector("main");
      const h = document.documentElement;
      const body = document.body;
      return {
        lang: h.lang,
        canonical: document.querySelector('link[rel="canonical"]')?.href || null,
        alternate: Array.from(document.querySelectorAll('link[rel="alternate"][hreflang]')).map(x => [x.hreflang, x.href]),
        h1: Array.from(document.querySelectorAll("main h1")).map(x => x.textContent.trim()),
        hasBread: Boolean(document.querySelector("main nav.breadcrumbs")),
        hasFooter: Boolean(document.querySelector("footer")),
        hasHeader: Boolean(document.querySelector("header")),
        scripts: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(x => x.textContent),
        rankingRows: document.querySelectorAll("main table.research-table--ranking tbody tr").length,
        criteriaRows: document.querySelectorAll("main table.research-table--criteria tbody tr").length,
        affiliateHrefs: Array.from(m?.querySelectorAll("a[href]") || []).map(a => a.href).filter(url => url.includes("kpwfp.com")),
        mainText: m?.innerText || "",
        width: window.innerWidth,
        htmlScrollWidth: h.scrollWidth,
        bodyScrollWidth: body.scrollWidth,
        imageBreakages: Array.from(m?.querySelectorAll("img") || []).filter(x => !x.complete || x.naturalWidth === 0).map(x => x.src),
        cssLoaded: Array.from(document.styleSheets).some(x => (x.href || "").includes("style.css")),
      };
    }"""
    d = page.evaluate(js)
    if d["lang"] != expected_lang:
        record_fail(lang, width, "html-lang", d["lang"])
    if d["canonical"] != expected_url:
        record_fail(lang, width, "canonical", d["canonical"])
    if d["h1"] is None or len(d["h1"]) != 1:
        record_fail(lang, width, "h1", d["h1"])
    for k in ("hasBread", "hasFooter", "hasHeader", "cssLoaded"):
        if not d[k]:
            record_fail(lang, width, k, False)
    if d["rankingRows"] != 10:
        record_fail(lang, width, "ranking-rows", d["rankingRows"])
    if d["criteriaRows"] != 5:
        record_fail(lang, width, "criteria-rows", d["criteriaRows"])
    if max(d["htmlScrollWidth"], d["bodyScrollWidth"]) > width + 2:
        record_fail(lang, width, "horizontal-overflow", (d["htmlScrollWidth"], d["bodyScrollWidth"]))
    if "Admitad" not in d["mainText"]:
        record_fail(lang, width, "affiliate-disclosure-missing", "Admitad")
    expected_alt = {
        "ru": f"{BASE}/{SLUG}.html",
        "en": f"{BASE}/en/{SLUG}.html",
        "zh-CN": f"{BASE}/cn/{SLUG}.html",
        "x-default": f"{BASE}/{SLUG}.html",
    }
    alts = dict(d["alternate"])
    if any(alts.get(k) != v for k, v in expected_alt.items()):
        record_fail(lang, width, "hreflang", alts)
    if not d["scripts"]:
        record_fail(lang, width, "schema", "No JSON-LD")
    else:
        try:
            graph = json.loads(d["scripts"][0]).get("@graph", [])
            by_type = {n.get("@type"): n for n in graph if isinstance(n, dict)}
            if by_type.get("ItemList", {}).get("numberOfItems") != 10:
                record_fail(lang, width, "schema-itemlist", "not 10")
            if len(by_type.get("FAQPage", {}).get("mainEntity", [])) != 9:
                record_fail(lang, width, "schema-faq", "not 9")
            if by_type.get("Dataset", {}).get("sameAs") != CANON:
                record_fail(lang, width, "schema-dataset", "wrong canonical")
            if by_type.get("Article", {}).get("sameAs") != repo:
                record_fail(lang, width, "schema-article", "wrong language repo")
        except Exception as ex:
            record_fail(lang, width, "schema-json", repr(ex))
    expected_aff_count = 5 if lang == "ru" else 4
    if len(d["affiliateHrefs"]) != expected_aff_count:
        record_fail(lang, width, "affiliate-count", len(d["affiliateHrefs"]))
    for href in d["affiliateHrefs"]:
        u = urlparse(href)
        q = parse_qs(u.query)
        landing = unquote(q.get("ulp", [""])[0])
        if u.hostname != REFERRAL_HOST or u.path != REFERRAL_PATH or q.get("erid") != [ERID] or landing not in VALID_LANDING:
            record_fail(lang, width, "affiliate-url", href)
    # Source/origin status only. We intentionally DO NOT CLICK partner URLs.
    if d["imageBreakages"]:
        record_fail(lang, width, "broken-in-body-images", d["imageBreakages"])
    metrics.append({"lang": lang, "viewport": width, "h1": d["h1"],
        "htmlWidth": d["htmlScrollWidth"], "bodyWidth": d["bodyScrollWidth"],
        "rankingRows": d["rankingRows"], "affiliateLinks": len(d["affiliateHrefs"]),
        "imagesBroken": len(d["imageBreakages"]), "htmlLang": d["lang"],
        "canonical": d["canonical"], "hasBreadcrumbs": d["hasBread"]})


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    for lang, url, expected_lang, repo in PAGES:
        context = browser.new_context(viewport={"width": 1280, "height": 820}, locale="ru-RU")
        page = context.new_page()
        for width in (1280, 360, 390, 412):
            try:
                page.set_viewport_size({"width": width, "height": 820})
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                status = response.status if response else None
                if status != 200:
                    record_fail(lang, width, "http", status)
                page.wait_for_timeout(700)
                validate(page, lang, width, url, expected_lang, repo)
                if width in (1280, 390):
                    page.screenshot(path=str(OUTPUT / f"{lang}-{width}.png"), full_page=True,
                                    animations="disabled", timeout=60000)
                print(f"QA {lang} viewport={width}: HTTP={status} "
                      f"overflow={metrics[-1]['htmlWidth']}/{metrics[-1]['bodyWidth']} "
                      f"rankRows={metrics[-1]['rankingRows']}", flush=True)
            except Exception as exc:
                record_fail(lang, width, "exception", repr(exc))
        context.close()

    # GitHub renders Markdown into article.markdown-body. Verify the public
    # rendered presentation, rather than relying only on the raw README source.
    github_repos = [
        ("ru", "https://github.com/IndexResearch-ru/" + SLUG),
        ("en", "https://github.com/IndexResearch-ru/" + SLUG + "-en"),
        ("cn", "https://github.com/IndexResearch-ru/" + SLUG + "-cn"),
    ]
    for lang, url in github_repos:
        context = browser.new_context(viewport={"width": 1280, "height": 820}, locale="en-US")
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            http = response.status if response else None
            page.wait_for_timeout(1200)
            elem = page.locator("article.markdown-body")
            if elem.count() == 0:
                record_fail(lang, "github", "readme-not-rendered", f"HTTP {http}: article.markdown-body absent")
                continue
            for img in elem.locator("img").all():
                try:
                    img.scroll_into_view_if_needed(timeout=14000)
                    img.evaluate("(el) => { el.loading = 'eager'; }")
                    img.evaluate("(el) => el.decode().catch(() => null)")
                except Exception as exc:
                    record_fail(lang, "github", "image-probe", repr(exc))
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(250)
            vals = elem.evaluate("""el => ({
                text: el.innerText,
                tables: el.querySelectorAll("table").length,
                images: Array.from(el.querySelectorAll("img")).map(i => ({
                    src: i.currentSrc || i.src, loaded: i.complete && i.naturalWidth > 0
                })),
                affiliate: Array.from(el.querySelectorAll('a[href*="kpwfp.com"]')).length,
                links: Array.from(el.querySelectorAll('a[href]')).map(a => a.href)
            })""")
            if http != 200:
                record_fail(lang, "github", "http", http)
            if vals["tables"] < 2:
                record_fail(lang, "github", "tables", vals["tables"])
            if "97/100" not in vals["text"] or "88" not in vals["text"]:
                record_fail(lang, "github", "scores", "ranking score text not found")
            if "Admitad" not in vals["text"]:
                record_fail(lang, "github", "disclosure", "Admitad not rendered")
            if len(vals["images"]) < 2:
                record_fail(lang, "github", "images", len(vals["images"]))
            missing = [v["src"] for v in vals["images"] if not v["loaded"]]
            if missing:
                record_fail(lang, "github", "broken-images", missing)
            if vals["affiliate"] < 2:
                record_fail(lang, "github", "referral-links", vals["affiliate"])
            github_metrics.append({"lang": lang, "http": http, "url": url,
                "scoreVisible": "97/100" in vals["text"],
                "tables": vals["tables"], "images": len(vals["images"]),
                "brokenImages": len(missing), "affiliateAnchors": vals["affiliate"]})
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 820})
                page.wait_for_timeout(200)
                page.screenshot(path=str(OUTPUT / f"github-{lang}-{width}.png"),
                                full_page=True, animations="disabled", timeout=60000)
            print(f"GITHUB_RENDER {lang}: HTTP={http}, tables={vals['tables']}, "
                  f"images={len(vals['images'])}, broken={len(missing)}, "
                  f"referral={vals['affiliate']}", flush=True)
        except Exception as exc:
            record_fail(lang, "github", "exception", repr(exc))
        finally:
            context.close()
    browser.close()

report = {"subject": SLUG, "testedViewportWidths": [1280, 360, 390, 412],
          "pages": [x[1] for x in PAGES], "measurements": metrics, "githubReadme": github_metrics, "errors": failures,
          "referralNote": "Partner URLs checked as DOM strings only; no affiliate clicks or destination redirects performed",
          "passed": len(failures) == 0}
(OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("LIVE_BROWSER_QA_REPORT=" + json.dumps(report, ensure_ascii=False), flush=True)
if failures:
    raise SystemExit(f"FAILED {len(failures)} checks")
print("PASSED all live-browser checks for three localized pages", flush=True)
