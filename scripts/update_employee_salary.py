from __future__ import annotations

from typing import Any

import pandas as pd

from mops_common import (
    DATA_DIR,
    clean_text,
    default_report_year,
    find_col,
    flatten_columns,
    read_tables,
    request_post,
    safe_int,
    to_salary_wan,
    write_json,
)

OUT = DATA_DIR / "employee_salary_disclosure.json"


def get_salary_html(typek: str, year: str) -> str:
    # TYPEK: sii = listed, otc = OTC. The front end does not distinguish them;
    # this script merges both into one JSON.
    payload = {
        "step": "1",
        "firstin": "1",
        "TYPEK": typek,
        "RYEAR": year,
        "code": "",
        "isnew": "false",
    }
    return request_post("ajax_t100sb15", payload)


def pick_main_table(tables: list[pd.DataFrame]) -> pd.DataFrame | None:
    for df in tables:
        cols = " ".join(flatten_columns(df))
        if "公司代號" in cols and "公司名稱" in cols and ("員工" in cols or "薪資" in cols):
            return df
    return tables[0] if tables else None


def parse_salary_table(df: pd.DataFrame, year: str, market: str) -> list[dict[str, Any]]:
    df = df.copy()
    df.columns = flatten_columns(df)
    cols = list(df.columns)

    industry_col = find_col(cols, ["產業"], []) or cols[0]
    code_col = find_col(cols, ["公司代號"], [])
    name_col = find_col(cols, ["公司名稱"], [])
    employees_col = find_col(cols, ["員工", "人數"], [])

    avg_latest_col = (
        find_col(cols, ["薪資", "平均"], ["同業", "前一", "較前", "減少", "低於"])
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

        rows.append({
            "年度": year,
            "市場別": market,
            "產業別": industry,
            "公司代號": code,
            "統一編號": "",
            "公司名稱": company,
            "員工人數": safe_int(row.get(employees_col, "")) if employees_col else "—",
            "平均薪資最近一年": to_salary_wan(row.get(avg_latest_col, "")) if avg_latest_col else None,
            "平均薪資前一年": to_salary_wan(row.get(avg_previous_col, "")) if avg_previous_col else None,
            "薪資中位數最近一年": to_salary_wan(row.get(median_latest_col, "")) if median_latest_col else None,
            "薪資中位數前一年": to_salary_wan(row.get(median_previous_col, "")) if median_previous_col else None,
        })
    return rows


def main() -> None:
    year = default_report_year()
    all_rows: list[dict[str, Any]] = []

    for typek, market in [("sii", "上市"), ("otc", "上櫃")]:
        html = get_salary_html(typek, year)
        tables = read_tables(html)
        table = pick_main_table(tables)
        if table is None:
            print(f"No salary table found for {market} {year}")
            continue
        rows = parse_salary_table(table, year, market)
        print(f"{market} {year}: {len(rows)} rows")
        all_rows.extend(rows)

    if not all_rows:
        raise RuntimeError("No salary disclosure rows were fetched. Check MOPS payload or page structure.")

    write_json(
        OUT,
        all_rows,
        f"MOPS 非擔任主管職務之全時員工薪資資訊，自動更新年度 {year}",
    )
    print(f"Wrote {len(all_rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
