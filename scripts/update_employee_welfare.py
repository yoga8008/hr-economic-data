from __future__ import annotations

import json
import os
import re
from typing import Any

from bs4 import BeautifulSoup

from mops_common import DATA_DIR, MopsBrowser, clean_text, read_tables, report_year_candidates, sleep_polite, write_json

SALARY_JSON = DATA_DIR / "employee_salary_disclosure.json"
WELFARE_JSON = DATA_DIR / "employee_welfare_disclosure.json"


def load_company_list() -> list[dict[str, str]]:
    """Use salary disclosure JSON as company universe, so welfare scraping is automatic."""
    if not SALARY_JSON.exists():
        return []
    payload = json.loads(SALARY_JSON.read_text(encoding="utf-8"))
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    seen = set()
    companies: list[dict[str, str]] = []
    for row in rows:
        code = clean_text(row.get("公司代號", ""))
        company = clean_text(row.get("公司名稱", ""))
        if not code or code in seen:
            continue
        seen.add(code)
        companies.append({"公司代號": code, "公司名稱": company})

    # 可用環境變數限制測試筆數，例如 MOPS_WELFARE_LIMIT=30
    limit = os.getenv("MOPS_WELFARE_LIMIT")
    if limit and limit.isdigit():
        return companies[: int(limit)]
    return companies


def run_visible_welfare_query(browser: MopsBrowser, code: str, year: str) -> str:
    browser.open_page("t100sb12")
    browser.fill_near_label(["年度", "申報年度", "查詢年度", "RYEAR", "year"], year)
    browser.fill_near_label(["公司", "公司代號", "證券代號", "簡稱", "代號", "code"], code)
    if not browser.click_query():
        browser.dump_debug(f"welfare_no_query_button_{year}_{code}")
        raise RuntimeError("找不到福利政策頁面的查詢按鈕")
    browser.ensure_not_security(f"welfare_security_{year}_{code}")
    return browser.combined_html()


def parse_welfare_html(html: str, code: str, company: str, year: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text("\n"))
    if not text or "查無" in text or "無資料" in text:
        return None

    welfare_policy = ""
    rights_protection = ""

    tables = read_tables(html)
    for df in tables:
        for _, row in df.iterrows():
            row_text = clean_text(" ".join(clean_text(x) for x in row.tolist()))
            if not row_text or len(row_text) < 8:
                continue
            if any(k in row_text for k in ["福利政策", "員工福利", "福利措施", "薪酬", "獎酬"]):
                welfare_policy += ("\n" if welfare_policy else "") + row_text
            if any(k in row_text for k in ["權益維護", "員工權益", "人權", "職業安全", "申訴", "安全衛生"]):
                rights_protection += ("\n" if rights_protection else "") + row_text

    if not welfare_policy and not rights_protection:
        # Fallback: keep meaningful page body and split if possible.
        parts = re.split(r"(權益維護措施|員工權益|人權政策|職業安全|安全衛生|申訴)", text, maxsplit=1)
        if len(parts) >= 3:
            welfare_policy = clean_text(parts[0])[:2000]
            rights_protection = clean_text("".join(parts[1:]))[:2000]
        else:
            welfare_policy = text[:2500]

    return {
        "年度": year,
        "公司代號": code,
        "統一編號": "",
        "公司名稱": company,
        "福利政策": welfare_policy[:3000] or "—",
        "權益維護措施": rights_protection[:3000] or "—",
    }


def main() -> None:
    companies = load_company_list()
    if not companies:
        raise RuntimeError("No company list found. Run update_employee_salary.py first so welfare update can use the company universe.")

    results: list[dict[str, Any]] = []
    years = report_year_candidates()
    with MopsBrowser() as browser:
        for i, item in enumerate(companies, start=1):
            code = item["公司代號"]
            company = item["公司名稱"]
            print(f"[{i}/{len(companies)}] {code} {company}")
            parsed = None
            for year in years:
                try:
                    html = run_visible_welfare_query(browser, code, year)
                    parsed = parse_welfare_html(html, code, company, year)
                    if parsed:
                        results.append(parsed)
                        break
                except Exception as exc:
                    print(f"Skip {code} {company} {year}: {exc}")
                sleep_polite(0.8)
            sleep_polite(1.2)

    if not results:
        raise RuntimeError("No welfare disclosure rows were fetched by visible UI operation. See _mops_debug artifact for screenshot/HTML.")

    write_json(
        WELFARE_JSON,
        results,
        "MOPS 員工福利政策及權益維護措施，純畫面操作自動更新",
    )
    print(f"Wrote {len(results)} rows to {WELFARE_JSON}")


if __name__ == "__main__":
    main()
