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
MOPS_SPA_BASE = f"{MOPS_ORIGIN}/mops/#/web"

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def taipei_now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def current_minguo_year() -> int:
    return taipei_now().year - 1911


def default_report_year() -> str:
    # 年度揭露通常查前一年度（例：2026 年查 114 年或依 MOPS 實際揭示年度調整）
    return os.getenv("MOPS_REPORT_YEAR") or str(current_minguo_year() - 1)


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
    ])


class MopsBrowser:
    """Use a real browser context so MOPS sees normal browser traffic."""

    def __init__(self) -> None:
        # 預設用 headless；若 MOPS 還是擋，可在 runner 環境變數設 MOPS_HEADLESS=false。
        self.headless = os.getenv("MOPS_HEADLESS", "true").lower() not in {"0", "false", "no"}
        self.channel_pref = os.getenv("MOPS_BROWSER_CHANNEL", "msedge")
        self._pw = None
        self.browser = None
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
                kwargs = {
                    "headless": self.headless,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if channel:
                    kwargs["channel"] = channel
                self.browser = self._pw.chromium.launch(**kwargs)
                print(f"Browser launched: {channel or 'bundled chromium'}, headless={self.headless}")
                break
            except Exception as exc:  # pragma: no cover
                last_error = exc
                print(f"Browser launch failed: {channel or 'bundled chromium'}: {exc}")

        if not self.browser:
            raise RuntimeError(f"Cannot launch browser. Last error: {last_error}")

        self.context = self.browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        self.page = self.context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()

    def warmup(self, page_code: str) -> None:
        assert self.page is not None
        url = f"{MOPS_SPA_BASE}/{page_code}"
        print(f"Open MOPS page: {url}")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            self.page.wait_for_timeout(2500)
        except PlaywrightTimeoutError:
            print("MOPS page load timeout; continue to try ajax fetch")

    def post(self, page_code: str, ajax_code: str, payload: dict[str, Any]) -> str:
        assert self.page is not None
        self.warmup(page_code)
        html = self.page.evaluate(
            """async ({ajaxCode, payload}) => {
                const params = new URLSearchParams();
                for (const [key, value] of Object.entries(payload)) {
                    params.append(key, value == null ? '' : String(value));
                }
                const response = await fetch(`/mops/web/${ajaxCode}`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'text/html, */*; q=0.01'
                    },
                    body: params.toString()
                });
                return await response.text();
            }""",
            {"ajaxCode": ajax_code, "payload": payload},
        )
        if is_security_page(html):
            raise RuntimeError("MOPS returned a security-block page even in browser mode. Try MOPS_HEADLESS=false or use another Taiwan network.")
        return html


def sleep_polite(seconds: float = 1.2) -> None:
    time.sleep(seconds)
