from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from mops_common import DATA_DIR, clean_text, default_report_year, read_tables, request_post, write_json

SALARY_JSON = DATA_DIR / "employee_salary_disclosure.json"
WELFARE_JSON = DATA_DIR / "employee_welfare_disclosure.json"


def load_company_list() -> list[dict[str, str]]:
    """Use the salary disclosure JSON as the company universe, so welfare scraping is automatic."""
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
    return companies


def fetch_welfare_html(code: str, year: str) -> str:
    # MOPS forms sometimes use slightly different keys. Try the common combinations.
    candidate_payloads = [
        {"step": "1", "firstin": "1", "co_id": code, "year": year, "TYPEK": "all"},
        {"step": "1", "firstin": "1", "co_id": code, "RYEAR": year, "TYPEK": "all"},
        {"step": "1", "firstin": "1", "code": code, "year": year, "TYPEK": "all"},
        {"step": "1", "firstin": "1", "COMPANY_ID": code, "S_YEAR": year},
    ]
    last_html = ""
    for payload in candidate_payloads:
        html = request_post("ajax_t100sb12", payload, sleep_sec=1.2)
        last_html = html
        text = clean_text(BeautifulSoup(html, "html.parser").get_text(" "))
        if code in text and len(text) > 200 and "查無" not in text:
            return html
    return last_html


def parse_welfare_html(html: str, code: str, company: str, year: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text("\n"))
    if not text or "查無" in text or "無資料" in text:
        return None

    welfare_policy = ""
    rights_protection = ""

    tables = read_tables(html)
    # First try table-style extraction.
    for df in tables:
        for _, row in df.iterrows():
            row_text = clean_text(" ".join(clean_text(x) for x in row.tolist()))
            if not row_text:
                continue
            if any(k in row_text for k in ["福利政策", "員工福利", "福利措施"]):
                welfare_policy += ("\n" if welfare_policy else "") + row_text
            if any(k in row_text for k in ["權益維護", "員工權益", "人權", "職業安全", "申訴"]):
                rights_protection += ("\n" if rights_protection else "") + row_text

    # Fallback: split the whole page text into two broad sections.
    if not welfare_policy and not rights_protection:
        parts = re.split(r"(權益維護措施|員工權益|人權政策|職業安全)", text, maxsplit=1)
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
    year = default_report_year()
    companies = load_company_list()
    if not companies:
        raise RuntimeError("No company list found. Run update_employee_salary.py first so welfare update can use the company universe.")

    results: list[dict[str, Any]] = []
    for i, item in enumerate(companies, start=1):
        code = item["公司代號"]
        company = item["公司名稱"]
        print(f"[{i}/{len(companies)}] {code} {company}")
        try:
            html = fetch_welfare_html(code, year)
            parsed = parse_welfare_html(html, code, company, year)
            if parsed:
                results.append(parsed)
        except Exception as exc:
            print(f"Skip {code} {company}: {exc}")

    if not results:
        raise RuntimeError("No welfare disclosure rows were fetched. Check MOPS payload or page structure.")

    write_json(
        WELFARE_JSON,
        results,
        f"MOPS 員工福利政策及權益維護措施，自動更新年度 {year}",
    )
    print(f"Wrote {len(results)} rows to {WELFARE_JSON}")


if __name__ == "__main__":
    main()
