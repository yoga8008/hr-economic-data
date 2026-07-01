from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

TAIPEI_TZ = timezone(timedelta(hours=8))
MOPS_ORIGIN = "https://mops.twse.com.tw"
MOPS_SPA_BASE = "https://mopsov.twse.com.tw/mops/web"

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
    try:
        return pd.read_html(html)
    except ValueError:
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
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    def open_page(self, page_code: str) -> None:
        assert self.page is not None
        url = f"{MOPS_SPA_BASE}/{page_code}"
        print(f"Open legacy MOPS page: {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(5000)
        self.dismiss_popups()
        try:
            print(f"Page title: {self.page.title()}")
        except Exception:
            pass

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
        return "\n".join(parts)

    def ensure_not_security(self, name: str) -> None:
        html = self.combined_html()
        if is_security_page(html):
            self.dump_debug(name)
            raise RuntimeError("MOPS returned a security-block page during UI operation.")
