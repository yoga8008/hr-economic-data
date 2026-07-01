from __future__ import annotations

import json
import os
import re
import time
from io import StringIO
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

TAIPEI_TZ = timezone(timedelta(hours=8))
MOPS_ORIGIN = "https://mops.twse.com.tw"
MOPS_SPA_BASE = f"{MOPS_ORIGIN}/mops/#/web"

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEBUG_DIR = ROOT / "_mops_debug"
DATA_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)


def taipei_now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def current_minguo_year() -> int:
    return taipei_now().year - 1911


def report_year_candidates() -> list[str]:
    """Try configured year first; otherwise try latest likely disclosure year and previous year.

    Example: in 2026, try 114 first, then 113.  This avoids hard failure before the
    newest annual disclosure is released.
    """
    configured = os.getenv("MOPS_REPORT_YEAR")
    if configured:
        return [configured]
    latest = current_minguo_year() - 1
    return [str(latest), str(latest - 1)]


def default_report_year() -> str:
    return report_year_candidates()[0]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def to_number(value: Any) -> float | None:
    text = clean_text(value)
    if not text or text in {"—", "-", "--"}:
        return None
    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def to_salary_wan(value: Any) -> float | None:
    """Convert MOPS salary values to NT$10k/person when source is likely NT$1k/person."""
    num = to_number(value)
    if num is None:
        return None
    # MOPS 常見薪資單位為千元；例如 4715 = 471.5 萬元
    if abs(num) > 1000:
        return round(num / 10, 1)
    return round(num, 1)


def safe_int(value: Any) -> int | str:
    num = to_number(value)
    if num is None:
        return "—"
    return int(round(num))


def flatten_columns(df: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for col in df.columns:
        if isinstance(col, tuple):
            cols.append(clean_text(" ".join(str(x) for x in col if str(x) != "nan")))
        else:
            cols.append(clean_text(col))
    return cols


def read_tables(html: str) -> list[pd.DataFrame]:
    """Read HTML tables from an HTML string.

    On Windows / newer pandas combinations, passing a raw HTML string can be
    interpreted as a file path and raise: [Errno 2] No such file or directory:
    <!DOCTYPE html>...  Wrapping with StringIO forces pandas to parse content.
    """
    try:
        return pd.read_html(StringIO(html))
    except (ValueError, OSError):
        return []


def find_col(columns: Iterable[str], include: list[str], exclude: list[str] | None = None) -> str | None:
    exclude = exclude or []
    for col in columns:
        text = clean_text(col)
        if all(word in text for word in include) and not any(word in text for word in exclude):
            return col
    return None


def write_json(path: Path, data: list[dict[str, Any]], source: str) -> None:
    payload = {
        "source": source,
        "updatedAt": taipei_now().strftime("%Y-%m-%d %H:%M:%S Asia/Taipei"),
        "data": data,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_security_page(text: str) -> bool:
    return any(key in text for key in [
        "FOR SECURITY REASONS",
        "SECURITY REASONS",
        "頁面無法呈現",
        "因為安全性考量",
        "YOU COULD GO",
    ])


def sleep_polite(seconds: float = 1.2) -> None:
    time.sleep(seconds)


class MopsBrowser:
    """Use real visible browser UI and avoid direct ajax calls.

    This version does not POST directly to ajax_t100sb15/ajax_t100sb12.  It opens
    the MOPS web page, fills fields, clicks the visible query button, waits for
    the page's own JavaScript to load data, then reads the rendered table.
    """

    def __init__(self) -> None:
        self.headless = os.getenv("MOPS_HEADLESS", "false").lower() in {"1", "true", "yes"}
        self.channel_pref = os.getenv("MOPS_BROWSER_CHANNEL", "msedge")
        self.user_data_dir = os.getenv(
            "MOPS_BROWSER_PROFILE",
            str(ROOT / ".mops-browser-profile"),
        )
        self._pw = None
        self.context = None
        self.page = None
        self._captured_responses: list[dict[str, str]] = []
        self._capture_active = False

    def __enter__(self) -> "MopsBrowser":
        self._pw = sync_playwright().start()
        channels = []
        if self.channel_pref:
            channels.append(self.channel_pref)
        channels.extend(["msedge", "chrome", None])

        last_error: Exception | None = None
        for channel in channels:
            try:
                kwargs: dict[str, Any] = {
                    "headless": self.headless,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-web-security",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                    "locale": "zh-TW",
                    "timezone_id": "Asia/Taipei",
                    "viewport": {"width": 1600, "height": 1000},
                    "user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "ignore_https_errors": True,
                }
                if channel:
                    kwargs["channel"] = channel
                self.context = self._pw.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    **kwargs,
                )
                print(f"Browser launched: {channel or 'bundled chromium'}, headless={self.headless}, UI-only=True")
                break
            except Exception as exc:  # pragma: no cover
                last_error = exc
                print(f"Browser launch failed: {channel or 'bundled chromium'}: {exc}")

        if not self.context:
            raise RuntimeError(f"Cannot launch browser. Last error: {last_error}")

        self.context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            """
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        try:
            self.page.on("response", self._capture_mops_response)
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    def open_page(self, page_code: str) -> None:
        assert self.page is not None
        url = f"{MOPS_SPA_BASE}/{page_code}"
        print(f"Open MOPS page: {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(3000)
        self.dismiss_popups()

        # The new MOPS is a Vue SPA.  Direct /mops/web/t100sb15 may render only
        # the home/menu shell; use the hash route and, if needed, click the
        # matching in-page route link so the real query component is mounted.
        try:
            self.page.evaluate("code => { if (!location.hash.includes(code)) location.hash = '/web/' + code; }", page_code)
            self.page.wait_for_timeout(4500)
        except Exception:
            pass

        for selector in [f'a[href="#/web/{page_code}"]', f'a[href="/mops/#/web/{page_code}"]']:
            try:
                loc = self.page.locator(selector).first
                if loc.count() and loc.is_visible(timeout=1000):
                    loc.click(timeout=2500)
                    self.page.wait_for_timeout(5000)
                    break
            except Exception:
                pass

        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(3000)
        self.dismiss_popups()
        try:
            print(f"Page title: {self.page.title()}")
            print(f"Current URL: {self.page.url}")
        except Exception:
            pass

    def start_response_capture(self) -> None:
        """Start capturing MOPS query responses after the form is submitted."""
        self._captured_responses = []
        self._capture_active = True

    def stop_response_capture(self) -> None:
        self._capture_active = False

    def _capture_mops_response(self, response) -> None:
        """Capture MOPS XHR/HTML responses so data can be parsed even when Vue does not render a table."""
        if not getattr(self, "_capture_active", False):
            return
        try:
            url = response.url or ""
            if "mops" not in url:
                return
            lower_url = url.lower()
            if any(skip in lower_url for skip in ["/assets/", ".js", ".css", ".png", ".jpg", ".gif", "googletagmanager", "google-analytics"]):
                return
            headers = response.headers or {}
            ctype = (headers.get("content-type") or headers.get("Content-Type") or "").lower()
            if not any(x in ctype for x in ["text", "html", "json", "javascript", "plain", "xml"]):
                return
            body = response.text()
            if not body:
                return
            # Keep only potentially useful response bodies.
            useful = any(k in body for k in ["公司代號", "公司名稱", "薪資", "員工", "查無資料", "RYEAR", "t100sb15", "資料庫"])
            useful = useful or any(k in lower_url for k in ["t100sb15", "ajax", "api", "query"])
            if not useful:
                return
            if len(body) > 1500000:
                body = body[:1500000]
            self._captured_responses.append({"url": url, "content_type": ctype, "body": body})
            print(f"Captured MOPS response: {url} ({len(body)} chars)")
        except Exception as exc:
            try:
                print(f"Capture response skipped: {exc}")
            except Exception:
                pass

    def captured_response_text(self) -> str:
        parts = []
        for item in getattr(self, "_captured_responses", []):
            parts.append(f"\n<!-- MOPS_CAPTURED_RESPONSE url={item.get('url','')} content_type={item.get('content_type','')} -->\n")
            parts.append(item.get("body", ""))
        return "\n".join(parts)

    def dismiss_popups(self) -> None:
        assert self.page is not None
        for text in ["同意", "確認", "確定", "關閉", "我知道了", "OK", "close"]:
            try:
                loc = self.page.get_by_text(text, exact=False).first
                if loc.is_visible(timeout=800):
                    loc.click(timeout=1500)
                    self.page.wait_for_timeout(500)
            except Exception:
                pass

    def frames(self):
        assert self.page is not None
        # page.frames includes main frame; keep unique by url/name.
        frames = []
        seen = set()
        for frame in self.page.frames:
            key = (frame.url, frame.name)
            if key not in seen:
                seen.add(key)
                frames.append(frame)
        return frames

    def dump_debug(self, name: str) -> None:
        assert self.page is not None
        stamp = taipei_now().strftime("%Y%m%d_%H%M%S")
        html_path = DEBUG_DIR / f"{stamp}_{name}.html"
        png_path = DEBUG_DIR / f"{stamp}_{name}.png"
        try:
            html_path.write_text(self.page.content(), encoding="utf-8")
            print(f"Debug HTML: {html_path}")
        except Exception as exc:
            print(f"Cannot save debug HTML: {exc}")
        try:
            self.page.screenshot(path=str(png_path), full_page=True)
            print(f"Debug screenshot: {png_path}")
        except Exception as exc:
            print(f"Cannot save debug screenshot: {exc}")

    def fill_near_label(self, keywords: list[str], value: str) -> bool:
        """Fill native input/select controls whose nearby text matches keywords."""
        script = r"""
        ({keywords, value}) => {
          const kws = keywords.map(k => String(k).toLowerCase());
          const visible = el => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const txt = el => (el && (el.innerText || el.textContent || '') || '').replace(/\s+/g, ' ').trim();
          const nearbyText = el => {
            let out = [el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('name'), el.getAttribute('id'), el.getAttribute('title')].filter(Boolean).join(' ');
            if (el.id) {
              const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
              if (lab) out += ' ' + txt(lab);
            }
            let p = el;
            for (let i = 0; i < 4 && p; i++, p = p.parentElement) out += ' ' + txt(p);
            const prev = el.previousElementSibling;
            const next = el.nextElementSibling;
            if (prev) out += ' ' + txt(prev);
            if (next) out += ' ' + txt(next);
            return out.toLowerCase();
          };
          const setNativeValue = (el, val) => {
            const setter = Object.getOwnPropertyDescriptor(el.__proto__, 'value')?.set;
            if (setter) setter.call(el, val); else el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
          };
          const controls = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea, select')).filter(visible);
          for (const el of controls) {
            const context = nearbyText(el);
            if (!kws.some(k => context.includes(k))) continue;
            if (el.tagName.toLowerCase() === 'select') {
              const options = Array.from(el.options || []);
              let opt = options.find(o => txt(o).includes(value) || String(o.value).includes(value));
              if (!opt && (value === '' || value === '全部')) opt = options.find(o => txt(o).includes('全部') || txt(o).includes('全'));
              if (opt) {
                el.value = opt.value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
              }
            } else {
              setNativeValue(el, value);
              return true;
            }
          }
          return false;
        }
        """
        for frame in self.frames():
            try:
                if frame.evaluate(script, {"keywords": keywords, "value": value}):
                    return True
            except Exception:
                continue
        return False

    def select_option_by_text(self, keywords: list[str], option_text: str) -> bool:
        """Select native select option near a label; fallback to visible custom dropdown text."""
        if self.fill_near_label(keywords, option_text):
            return True
        # Custom select fallback: click a field near label, then click option text.
        assert self.page is not None
        for kw in keywords:
            try:
                self.page.get_by_text(kw, exact=False).first.click(timeout=1200)
                self.page.wait_for_timeout(300)
                self.page.get_by_text(option_text, exact=False).first.click(timeout=1800)
                self.page.wait_for_timeout(500)
                return True
            except Exception:
                pass
        return False


    def fill_salary_query_form(self, year: str, market: str | None = None, industry: str = "全部產業") -> bool:
        """Fill t100sb15 form with real Playwright UI operations.

        The MOPS Vue page uses visible controls.  Earlier DOM value setting could
        appear successful but not update Vue state, so this method uses click/fill/
        select_option first, and only falls back to DOM events when necessary.
        """
        assert self.page is not None
        page = self.page
        self.dismiss_popups()

        # Wait until the real query component is mounted.
        mounted = False
        for _ in range(30):
            try:
                if page.get_by_text("查詢條件", exact=False).count() or page.locator("input[placeholder*='101']").count():
                    mounted = True
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)
        if not mounted:
            print("Salary form not mounted yet; continue with fallback selectors")

        def is_bad_global_input(loc) -> bool:
            try:
                meta = loc.evaluate("el => [el.id, el.name, el.placeholder, el.getAttribute('aria-label')].filter(Boolean).join(' ')")
                return bool(re.search(r"searchInfo|搜尋|關鍵字|公司代號/名稱/關鍵字", str(meta), re.I))
            except Exception:
                return False

        def fill_year_with_locator(frame) -> tuple[bool, str]:
            selectors = [
                "input[placeholder*='101']",
                "input[placeholder*='年']",
                "input[placeholder*='請輸入']",
                "input:not([type='hidden'])",
            ]
            tried = []
            for selector in selectors:
                try:
                    locs = frame.locator(selector)
                    count = min(locs.count(), 10)
                except Exception:
                    continue
                for idx in range(count):
                    loc = locs.nth(idx)
                    try:
                        if not loc.is_visible(timeout=800):
                            continue
                        if is_bad_global_input(loc):
                            continue
                        meta = loc.evaluate("el => [el.id, el.name, el.placeholder, el.className].filter(Boolean).join('|')")
                        tried.append(str(meta))
                        loc.scroll_into_view_if_needed(timeout=3000)
                        loc.click(timeout=3000)
                        # Clear using keyboard; this triggers framework listeners better than raw JS.
                        loc.press("Control+A", timeout=2000)
                        loc.press("Backspace", timeout=2000)
                        loc.type(str(year), delay=60, timeout=5000)
                        loc.press("Tab", timeout=2000)
                        page.wait_for_timeout(500)
                        val = loc.input_value(timeout=2000)
                        if str(year) in str(val):
                            return True, f"{selector}[{idx}]={meta}, value={val}"
                        # Last resort: native setter plus events.
                        loc.evaluate(
                            """
                            (el, val) => {
                              const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
                              if (setter) setter.call(el, val); else el.value = val;
                              for (const evt of ['input','change','keyup','blur']) el.dispatchEvent(new Event(evt, {bubbles:true}));
                            }
                            """,
                            str(year),
                        )
                        page.wait_for_timeout(500)
                        val = loc.input_value(timeout=2000)
                        if str(year) in str(val):
                            return True, f"{selector}[{idx}]={meta}, value={val}, js-set"
                    except Exception as exc:
                        tried.append(f"{selector}[{idx}] error={exc}")
                        continue
            return False, "; ".join(tried[-8:])

        def select_native(frame, nth: int, wanted: str) -> tuple[bool, str]:
            try:
                locs = frame.locator("select")
                if locs.count() <= nth:
                    return False, f"select count={locs.count()}"
                loc = locs.nth(nth)
                if not loc.is_visible(timeout=1000):
                    return False, f"select {nth} not visible"
                opts = loc.evaluate("el => Array.from(el.options || []).map(o => ({label:o.textContent.trim(), value:o.value}))")
                # Prefer exact/contains label or value.
                target = None
                for opt in opts:
                    label = str(opt.get('label','')).replace(' ', '').replace('\u3000','')
                    value = str(opt.get('value','')).replace(' ', '').replace('\u3000','')
                    want = str(wanted).replace(' ', '').replace('\u3000','')
                    if want and (want in label or want in value):
                        target = opt
                        break
                if not target and ('全部' in wanted or wanted == ''):
                    for opt in opts:
                        if '全部' in str(opt.get('label','')) or '全' == str(opt.get('label','')).strip():
                            target = opt
                            break
                if not target:
                    return False, f"no option {wanted}; options={opts[:8]}"
                loc.select_option(value=str(target['value']), timeout=5000)
                loc.dispatch_event("change")
                return True, f"select{nth}={target}"
            except Exception as exc:
                return False, f"select{nth} error={exc}"

        result = {
            "marketSet": False,
            "industrySet": False,
            "yearSet": False,
            "details": [],
        }

        for frame in self.frames():
            try:
                # The t100sb15 form currently has market select first and industry select second.
                if market:
                    ok, detail = select_native(frame, 0, market)
                    result["marketSet"] = result["marketSet"] or ok
                    result["details"].append(detail)
                else:
                    result["marketSet"] = True

                ok, detail = select_native(frame, 1, industry)
                result["industrySet"] = result["industrySet"] or ok or True
                result["details"].append(detail)

                ok, detail = fill_year_with_locator(frame)
                result["yearSet"] = result["yearSet"] or ok
                result["details"].append(detail)

                if result["yearSet"]:
                    print(f"Filled salary form by UI: {result}")
                    page.wait_for_timeout(1000)
                    return True
            except Exception as exc:
                print(f"Fill salary form UI failed in frame: {exc}")
                continue

        # DOM fallback, keeping the previous generic logic for unexpected layouts.
        script = r"""
        ({year, market, industry}) => {
          const visible = el => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const txt = el => (el && (el.innerText || el.textContent || '') || '').replace(/[\s\u00a0\u3000]+/g, ' ').trim();
          const setNativeValue = (el, val) => {
            const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
            if (setter) setter.call(el, val); else el.value = val;
            for (const evt of ['input','change','keyup','blur']) el.dispatchEvent(new Event(evt, { bubbles: true }));
          };
          const selects = Array.from(document.querySelectorAll('select')).filter(visible);
          const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea')).filter(visible)
            .filter(i => !/searchInfo|搜尋|關鍵字/.test([i.id,i.name,i.placeholder].filter(Boolean).join(' ')));
          if (market && selects[0]) {
            const want = String(market).replace(/[\s\u00a0\u3000]+/g, '');
            const opt = Array.from(selects[0].options || []).find(o => (o.textContent || o.value || '').replace(/[\s\u00a0\u3000]+/g, '').includes(want));
            if (opt) { selects[0].value = opt.value; selects[0].dispatchEvent(new Event('change', {bubbles:true})); }
          }
          if (selects[1]) {
            const opt = Array.from(selects[1].options || []).find(o => (o.textContent || '').includes('全部'));
            if (opt) { selects[1].value = opt.value; selects[1].dispatchEvent(new Event('change', {bubbles:true})); }
          }
          const yearInput = inputs.find(i => /101|年|請輸入|年度/.test([i.placeholder,i.id,i.name,txt(i.parentElement)].filter(Boolean).join(' '))) || inputs[0];
          if (yearInput) setNativeValue(yearInput, String(year));
          return {yearSet: !!yearInput, inputValue: yearInput ? yearInput.value : '', inputCount: inputs.length, selectCount: selects.length};
        }
        """
        for frame in self.frames():
            try:
                fallback = frame.evaluate(script, {"year": year, "market": market, "industry": industry})
                if isinstance(fallback, dict) and fallback.get("yearSet"):
                    print(f"Filled salary form by fallback DOM: {fallback}")
                    page.wait_for_timeout(1000)
                    return True
            except Exception as exc:
                print(f"Fill salary fallback failed in frame: {exc}")
        print(f"Fill salary form failed: {result}")
        return False

    def click_salary_query_button(self) -> bool:
        """Click the real bottom-right query button on t100sb15."""
        assert self.page is not None
        page = self.page

        try:
            state = page.evaluate(r"""
            () => Array.from(document.querySelectorAll('select, input:not([type=hidden])')).filter(el => {
              const r = el.getBoundingClientRect();
              const st = getComputedStyle(el);
              return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
            }).map((el, idx) => ({
              idx, tag: el.tagName, id: el.id, name: el.name, placeholder: el.getAttribute('placeholder'), value: el.value,
              text: el.tagName === 'SELECT' ? Array.from(el.options || []).find(o => o.selected)?.textContent?.trim() : ''
            })).slice(0, 10)
            """)
            print(f"Salary form state before query: {state}")
        except Exception as exc:
            print(f"Cannot print salary form state before query: {exc}")

        # Try Playwright locators first.
        for frame in self.frames():
            try:
                locs = frame.locator("button:has-text('查詢'), input[type='button'][value*='查詢'], input[type='submit'][value*='查詢']")
                visible_locs = []
                for i in range(min(locs.count(), 20)):
                    loc = locs.nth(i)
                    try:
                        if loc.is_visible(timeout=800):
                            box = loc.bounding_box(timeout=1000)
                            text = loc.inner_text(timeout=1000) if loc.evaluate("el => el.tagName.toLowerCase() !== 'input'") else loc.get_attribute('value')
                            visible_locs.append((loc, box, text))
                    except Exception:
                        continue
                if visible_locs:
                    # lowest button is the form action button in this page.
                    visible_locs.sort(key=lambda x: (x[1] or {}).get('y', 0), reverse=True)
                    loc, box, label = visible_locs[0]
                    loc.scroll_into_view_if_needed(timeout=3000)
                    loc.click(timeout=5000)
                    print(f"Clicked salary query button by locator: text={label}, box={box}")
                    page.wait_for_timeout(12000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=25000)
                    except Exception:
                        pass
                    page.wait_for_timeout(6000)
                    try:
                        print(f"Captured response count after query: {len(getattr(self, '_captured_responses', []))}")
                    except Exception:
                        pass
                    return True
            except Exception as exc:
                print(f"Click salary query locator failed in frame: {exc}")

        # JS fallback.
        script = r"""
        () => {
          const visible = el => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const rawText = el => [el.innerText, el.textContent, el.value, el.getAttribute('aria-label'), el.getAttribute('title')].filter(Boolean).join(' ');
          const compact = el => rawText(el).replace(/[\s\u00a0\u3000]+/g, '').trim();
          const candidates = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], a[role="button"], [role="button"]')).filter(visible);
          const exact = candidates.filter(el => compact(el) === '查詢' || compact(el).toLowerCase() === 'query' || compact(el).toLowerCase() === 'search');
          const pool = exact.length ? exact : candidates.filter(el => /查詢/.test(compact(el)));
          if (!pool.length) return { clicked:false, candidates:candidates.map(el => compact(el)).slice(0,30) };
          pool.sort((a,b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
          const btn = pool[0];
          btn.scrollIntoView({block:'center', inline:'center'});
          btn.click();
          return { clicked:true, text:compact(btn), top:btn.getBoundingClientRect().top };
        }
        """
        for frame in self.frames():
            try:
                result = frame.evaluate(script)
                if isinstance(result, dict) and result.get("clicked"):
                    print(f"Clicked salary query button by JS: {result}")
                    page.wait_for_timeout(12000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=25000)
                    except Exception:
                        pass
                    page.wait_for_timeout(6000)
                    try:
                        print(f"Captured response count after query: {len(getattr(self, '_captured_responses', []))}")
                    except Exception:
                        pass
                    return True
                elif isinstance(result, dict):
                    print(f"No salary query button candidates: {result}")
            except Exception as exc:
                print(f"Click salary query JS failed in frame: {exc}")
        return False

    def click_query(self) -> bool:
        """Click a visible 查詢/search button.

        MOPS buttons may render as "查 詢" or "查　詢" with spaces between
        Chinese characters.  Match both normal and compact text.  If a visible
        button still cannot be found, submit the nearest form as a final UI
        fallback instead of calling ajax endpoints directly.
        """
        script = r"""
        () => {
          const visible = el => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const rawText = el => [
              el.innerText,
              el.textContent,
              el.value,
              el.getAttribute('aria-label'),
              el.getAttribute('title'),
              el.getAttribute('alt'),
              el.getAttribute('name'),
              el.getAttribute('id')
            ].filter(Boolean).join(' ');
          const normalized = el => rawText(el).replace(/[\s\u00a0\u3000]+/g, ' ').trim();
          const compact = el => rawText(el).replace(/[\s\u00a0\u3000]+/g, '').trim();
          const candidates = Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"], input[type="image"], [role="button"], .btn, .button'));
          for (const el of candidates) {
            if (!visible(el)) continue;
            const t = normalized(el);
            const c = compact(el);
            const onclick = String(el.getAttribute('onclick') || '');
            if (/查詢|搜尋|送出|Query|Search|query|submit/i.test(t) || /查詢|搜尋|送出/.test(c) || /query|search|submit|ajax/i.test(onclick)) {
              el.scrollIntoView({block:'center', inline:'center'});
              el.click();
              return true;
            }
          }

          // Final UI fallback: submit a visible form containing RYEAR/year fields.
          const forms = Array.from(document.querySelectorAll('form')).filter(visible);
          for (const form of forms) {
            const formText = (form.innerText || form.textContent || form.outerHTML || '').replace(/[\s\u00a0\u3000]+/g, '');
            if (/年度|RYEAR|公司代號|產業/.test(formText)) {
              form.dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}));
              if (typeof form.submit === 'function') form.submit();
              return true;
            }
          }
          return false;
        }
        """
        for frame in self.frames():
            try:
                if frame.evaluate(script):
                    assert self.page is not None
                    self.page.wait_for_timeout(4500)
                    try:
                        self.page.wait_for_load_state("networkidle", timeout=12000)
                    except Exception:
                        pass
                    self.page.wait_for_timeout(2500)
                    return True
            except Exception:
                continue
        return False

    def combined_html(self) -> str:
        assert self.page is not None
        parts = []
        for frame in self.frames():
            try:
                parts.append(frame.content())
            except Exception:
                pass
        captured = self.captured_response_text()
        if captured:
            parts.append(captured)
        return "\n".join(parts)


    def visible_body_text(self) -> str:
        assert self.page is not None
        texts = []
        for frame in self.frames():
            try:
                txt = frame.locator("body").inner_text(timeout=3000)
                if txt:
                    texts.append(txt)
            except Exception:
                pass
        return "\n".join(texts)

    def ensure_not_security(self, name: str) -> None:
        html = self.combined_html()
        if is_security_page(html):
            self.dump_debug(name)
            raise RuntimeError("MOPS returned a security-block page during UI operation.")
