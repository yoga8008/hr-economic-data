from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

TAIPEI_TZ = timezone(timedelta(hours=8))
MOPS_BASE = "https://mopsov.twse.com.tw/mops/web"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def taipei_now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def current_minguo_year() -> int:
    return taipei_now().year - 1911


def default_report_year() -> str:
    # Annual disclosures usually refer to the preceding year.
    return str(current_minguo_year() - 1)


def _page_for_ajax(path: str) -> str:
    if path.startswith("ajax_"):
        return path.replace("ajax_", "", 1)
    return path


def _is_security_page(text: str) -> bool:
    return "FOR SECURITY REASONS" in text or "頁面無法呈現" in text or "SECURITY REASONS" in text


def request_post(path: str, payload: dict[str, Any], timeout: int = 30, sleep_sec: float = 0.8) -> str:
    ajax_url = f"{MOPS_BASE}/{path}"
    page = _page_for_ajax(path)
    page_url = f"{MOPS_BASE}/{page}"

    # Warm up the normal page first so MOPS can issue cookies/session state.
    time.sleep(sleep_sec)
    warmup = SESSION.get(page_url, timeout=timeout)
    warmup.encoding = "utf-8"

    headers = dict(HEADERS)
    headers["Referer"] = page_url
    headers["Origin"] = "https://mopsov.twse.com.tw"
    headers["X-Requested-With"] = "XMLHttpRequest"

    time.sleep(sleep_sec)
    res = SESSION.post(ajax_url, data=payload, headers=headers, timeout=timeout)
    res.raise_for_status()
    res.encoding = "utf-8"
    if _is_security_page(res.text):
        raise RuntimeError(
            "MOPS returned a security-block page. "
            "GitHub-hosted runners are often blocked; use a self-hosted runner from a normal Taiwan network/IP."
        )
    return res.text


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
    # MOPS commonly displays salary in NT$1k/person. 4715 => 471.5 萬元.
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
