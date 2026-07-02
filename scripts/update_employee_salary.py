# version: salary browser AJAX old-endpoint fallback - 2026-07-01
from __future__ import annotations

from typing import Any
import re
import json

import pandas as pd

from mops_common import (
    DATA_DIR,
    MopsBrowser,
    clean_text,
    find_col,
    flatten_columns,
    read_tables,
    report_year_candidates,
    safe_int,
    sleep_polite,
    to_salary_wan,
    write_json,
)

OUT = DATA_DIR / "employee_salary_disclosure.json"


def pick_main_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    candidates: list[pd.DataFrame] = []
    for df in tables:
        cols = " ".join(flatten_columns(df))
        body = " ".join(clean_text(x) for x in df.astype(str).head(3).to_numpy().ravel())
        haystack = cols + " " + body
        if "公司代號" in haystack and "公司名稱" in haystack and ("員工" in haystack or "薪資" in haystack):
            candidates.append(df)
    if candidates:
        return max(candidates, key=lambda x: len(x))
    return max(tables, key=lambda x: len(x)) if tables else None


def parse_salary_table(df: pd.DataFrame, year: str, market: str) -> list[dict[str, Any]]:
    df = df.copy()
    df.columns = flatten_columns(df)
    cols = list(df.columns)

    industry_col = find_col(cols, ["產業"], []) or find_col(cols, ["類別"], []) or cols[0]
    code_col = find_col(cols, ["公司代號"], []) or find_col(cols, ["代號"], [])
    name_col = find_col(cols, ["公司名稱"], []) or find_col(cols, ["名稱"], [])
    employees_col = find_col(cols, ["員工", "人數"], []) or find_col(cols, ["人數"], [])

    avg_latest_col = (
        find_col(cols, ["平均"], ["同業", "前一", "較前", "減少", "低於", "中位"])
        or find_col(cols, ["平均數"], ["同業", "前一", "較前", "減少", "低於"])
    )
    avg_previous_col = find_col(cols, ["平均", "前"], ["同業"])
    median_latest_col = find_col(cols, ["中位數"], ["前一", "較前"])
    median_previous_col = find_col(cols, ["中位數", "前"], [])

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        code = clean_text(row.get(code_col, "")) if code_col else ""
        company = clean_text(row.get(name_col, "")) if name_col else ""
        industry = clean_text(row.get(industry_col, "")) if industry_col else ""
        if not code or not company or "公司代號" in code or "公司名稱" in company:
            continue
        # Sometimes code comes as 2330.0 after pandas parsing.
        code_num = code.replace(".0", "")
        if not code_num.isdigit() or len(code_num) < 4:
            continue

        rows.append({
            "年度": year,
            "市場別": market,
            "產業別": industry,
            "公司代號": code_num,
            "統一編號": "",
            "公司名稱": company,
            "員工人數": safe_int(row.get(employees_col, "")) if employees_col else "—",
            "平均薪資最近一年": to_salary_wan(row.get(avg_latest_col, "")) if avg_latest_col else None,
            "平均薪資前一年": to_salary_wan(row.get(avg_previous_col, "")) if avg_previous_col else None,
            "薪資中位數最近一年": to_salary_wan(row.get(median_latest_col, "")) if median_latest_col else None,
            "薪資中位數前一年": to_salary_wan(row.get(median_previous_col, "")) if median_previous_col else None,
        })
    return rows




def parse_salary_text(text: str, year: str, market: str) -> list[dict[str, Any]]:
    """Fallback parser for Vue-rendered tables that are not HTML <table> elements.

    It scans visible body text, finds 4-digit company codes, and uses neighboring
    tokens as industry/company/salary fields. This is intentionally conservative:
    rows without a 4-digit company code and enough following numeric values are skipped.
    """
    text = clean_text(text)
    if "公司代號" not in text or "公司名稱" not in text:
        return []

    tokens = [t for t in re.split(r"\s+", text) if t]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    header_words = {"市場別", "產業別", "年度", "查詢", "清除設定", "公司代號", "公司名稱", "員工人數"}

    for i, tok in enumerate(tokens):
        code = tok.replace(".0", "")
        if not re.fullmatch(r"\d{4}", code):
            continue
        if code in seen:
            continue

        prev = tokens[i - 1] if i >= 1 else ""
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if not nxt or nxt in header_words:
            continue
        # Avoid menu links / examples such as "例：101年請輸入101".
        if prev in header_words or "例" in prev or "輸入" in prev:
            continue

        # Collect numeric fields after company name until next company code.
        j = i + 2
        nums: list[str] = []
        while j < len(tokens):
            t = tokens[j]
            if re.fullmatch(r"\d{4}", t.replace(".0", "")) and len(nums) >= 2:
                break
            if re.search(r"\d", t) and not re.search(r"年|%|：|:", t):
                nums.append(t)
            if len(nums) >= 8:
                break
            j += 1

        if len(nums) < 3:
            continue

        rows.append({
            "年度": year,
            "市場別": market,
            "產業別": prev,
            "公司代號": code,
            "統一編號": "",
            "公司名稱": nxt,
            "員工人數": safe_int(nums[0]),
            "平均薪資最近一年": to_salary_wan(nums[1]) if len(nums) > 1 else None,
            "平均薪資前一年": to_salary_wan(nums[2]) if len(nums) > 2 else None,
            "薪資中位數最近一年": to_salary_wan(nums[3]) if len(nums) > 3 else None,
            "薪資中位數前一年": to_salary_wan(nums[4]) if len(nums) > 4 else None,
        })
        seen.add(code)

    return rows


def _find_value_by_keywords(d: dict[str, Any], keywords: list[str]) -> Any:
    for k, v in d.items():
        ks = clean_text(k)
        if any(word in ks for word in keywords):
            return v
    return ""


def _walk_json_records(obj: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        # A row usually has at least a company code/name and salary/employee fields.
        joined_keys = " ".join(clean_text(k) for k in obj.keys())
        joined_vals = " ".join(clean_text(v) for v in obj.values() if not isinstance(v, (dict, list)))
        if ("公司代號" in joined_keys or re.search(r"\b\d{4}\b", joined_vals)) and ("公司名稱" in joined_keys or "公司" in joined_keys):
            records.append(obj)
        for v in obj.values():
            records.extend(_walk_json_records(v))
    elif isinstance(obj, list):
        for item in obj:
            records.extend(_walk_json_records(item))
    return records


def parse_salary_json_payload(text: str, year: str, market: str) -> list[dict[str, Any]]:
    """Parse JSON payloads captured from MOPS XHR if the Vue page does not render a HTML table."""
    payloads: list[str] = []
    # Try full text first, then individual captured response blocks.
    payloads.append(text)
    payloads.extend(re.findall(r"<!-- MOPS_CAPTURED_RESPONSE[^>]*-->\s*(.*?)(?=\n<!-- MOPS_CAPTURED_RESPONSE|\Z)", text, flags=re.S))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        payload = payload.strip()
        if not payload or not (payload.startswith("{") or payload.startswith("[")):
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        for rec in _walk_json_records(obj):
            code = clean_text(_find_value_by_keywords(rec, ["公司代號", "代號", "code", "co_id", "公司代碼"]))
            name = clean_text(_find_value_by_keywords(rec, ["公司名稱", "名稱", "name", "公司"]))
            if not code:
                # fallback: first 4-digit value in the row
                joined = " ".join(clean_text(v) for v in rec.values() if not isinstance(v, (dict, list)))
                m = re.search(r"\b\d{4}\b", joined)
                code = m.group(0) if m else ""
            code = code.replace(".0", "")
            if not re.fullmatch(r"\d{4}", code) or code in seen:
                continue
            seen.add(code)
            industry = clean_text(_find_value_by_keywords(rec, ["產業", "類別", "industry"]))
            employees = _find_value_by_keywords(rec, ["員工人數", "人數", "employee"])
            avg_latest = _find_value_by_keywords(rec, ["平均", "avg"])
            median_latest = _find_value_by_keywords(rec, ["中位", "median"])
            rows.append({
                "年度": year,
                "市場別": market,
                "產業別": industry,
                "公司代號": code,
                "統一編號": "",
                "公司名稱": name,
                "員工人數": safe_int(employees),
                "平均薪資最近一年": to_salary_wan(avg_latest),
                "平均薪資前一年": None,
                "薪資中位數最近一年": to_salary_wan(median_latest),
                "薪資中位數前一年": None,
            })
    return rows



def parse_salary_html(html: str, year: str, market: str) -> list[dict[str, Any]]:
    tables = read_tables(html)
    table = pick_main_table(tables)
    rows: list[dict[str, Any]] = []
    if table is not None:
        rows = parse_salary_table(table, year, market)
    if not rows:
        rows = parse_salary_json_payload(html, year, market)
    if not rows:
        rows = parse_salary_text(html, year, market)
    return rows


def run_browser_ajax_query(browser: MopsBrowser, year: str, market: str) -> str:
    typek_map = {"上市": "sii", "上櫃": "otc"}
    typek = typek_map.get(market, "sii")
    browser.open_page("t100sb15")
    print(f"POST old MOPS ajax_t100sb15 via browser session: market={market}, TYPEK={typek}, RYEAR={year}")
    html = browser.fetch_salary_ajax_html(year=year, typek=typek)
    if "FOR SECURITY REASONS" in html or "SECURITY REASONS" in html or "因為安全性考量" in html:
        browser.dump_debug(f"salary_ajax_security_{year}_{market}")
        raise RuntimeError("MOPS AJAX returned security page")
    if not html or ("公司代號" not in html and "公司名稱" not in html and "查無" not in html):
        browser.dump_debug(f"salary_ajax_unexpected_{year}_{market}")
        preview = clean_text(html[:300])
        raise RuntimeError(f"MOPS AJAX response did not contain salary table keywords: {preview}")
    return html

def run_visible_query(browser: MopsBrowser, year: str, market: str | None) -> str:
    browser.open_page("t100sb15")

    if not browser.fill_salary_query_form(year=year, market=market or "上市", industry="全部產業"):
        browser.dump_debug(f"salary_fill_failed_{year}_{market or 'default'}")
        raise RuntimeError("找不到薪資資訊頁面的年度／市場欄位")

    browser.start_response_capture()
    if not browser.click_salary_query_button():
        browser.dump_debug(f"salary_no_query_button_{year}_{market or 'default'}")
        raise RuntimeError("找不到薪資資訊頁面的查詢按鈕")

    browser.stop_response_capture()
    browser.ensure_not_security(f"salary_security_{year}_{market or 'default'}")
    html = browser.combined_html()
    if "公司代號" not in html and "公司名稱" not in html:
        browser.dump_debug(f"salary_no_table_{year}_{market or 'default'}")
    return html


def fetch_salary_rows_for_year(year: str) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    with MopsBrowser() as browser:
        # The actual data is on the old ajax endpoint.  We still open the SPA page
        # first to establish a normal browser session/cookies, then POST through
        # that browser context.
        for market in ["上市", "上櫃"]:
            rows: list[dict[str, Any]] = []
            try:
                html = run_browser_ajax_query(browser, year, market)
                rows = parse_salary_html(html, year, market)
                if rows:
                    print(f"Browser AJAX parsed {market} {year}: {len(rows)} rows")
                else:
                    print(f"Browser AJAX returned no parsed salary rows for {market} {year}; fallback to visible UI")
            except Exception as exc:
                print(f"Browser AJAX failed for {market} {year}: {exc}; fallback to visible UI")

            if not rows:
                try:
                    html = run_visible_query(browser, year, market)
                    rows = parse_salary_html(html + "\n" + browser.visible_body_text() + "\n" + browser.captured_response_text(), year, market)
                except Exception as exc:
                    print(f"Visible UI fallback failed for {market} {year}: {exc}")

            if not rows:
                print(f"No salary rows parsed for {market} {year}")
                browser.dump_debug(f"salary_no_rows_{year}_{market}")
                sleep_polite(1.0)
                continue

            fresh = []
            for row in rows:
                code = clean_text(row.get("公司代號", ""))
                key = f"{market}:{code}"
                if code and key not in seen_keys:
                    seen_keys.add(key)
                    fresh.append(row)
            print(f"{market} {year}: {len(fresh)} new rows")
            all_rows.extend(fresh)
            sleep_polite(1.0)

    return all_rows

def main() -> None:
    final_rows: list[dict[str, Any]] = []
    final_year = ""
    for year in report_year_candidates():
        print(f"Try salary disclosure year: {year}")
        rows = fetch_salary_rows_for_year(year)
        if rows:
            final_rows = rows
            final_year = year
            break
        print(f"No rows for year {year}; try next candidate if available.")

    if not final_rows:
        raise RuntimeError("No salary disclosure rows were fetched by visible UI operation. See _mops_debug artifact for screenshot/HTML.")

    write_json(
        OUT,
        final_rows,
        f"MOPS 非擔任主管職務之全時員工薪資資訊，純畫面操作自動更新年度 {final_year}",
    )
    print(f"Wrote {len(final_rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
