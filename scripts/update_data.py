import pandas as pd
from datetime import datetime
import os
import re
import io
import xml.etree.ElementTree as ET
import requests

# =====================================================
# 自動更新台灣 CPI 年增率、失業率
# 輸出：
# data/taiwan_cpi_unemployment.csv
# data/taiwan_cpi_unemployment.json
#
# 注意：
# 1. CPI 來源為主計總處統計表 Excel。
# 2. 失業率來源為政府資料開放平臺 XML。
# 3. 若官方檔案暫時抓不到，會使用 fallback_data，避免 GitHub Actions 失敗。
# 4. 若使用 CPI .xls，GitHub Actions 需安裝 xlrd：
#    pip install pandas openpyxl xlrd requests beautifulsoup4 lxml feedparser
# =====================================================

CPI_EXCEL_URL = "https://ws.dgbas.gov.tw/001/Upload/463/relfile/10315/2664/cpispl.xls"
UNEMPLOYMENT_XML_URL = "https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/230038/mp0101a07.xml"

# 保底資料：官方來源暫時無法抓取時使用
fallback_data = [

    ["2024/01", 2.43, 3.31],
    ["2024/02", 3.08, 3.39],
    ["2024/03", 2.14, 3.38],
    ["2024/04", 1.95, 3.36],
    ["2024/05", 2.24, 3.34],
    ["2024/06", 2.42, 3.37],
    ["2024/07", 2.52, 3.36],
    ["2024/08", 2.36, 3.38],
    ["2024/09", 1.82, 3.36],
    ["2024/10", 1.69, 3.37],
    ["2024/11", 2.08, 3.35],
    ["2024/12", 2.10, 3.32],

    ["2025/01", 2.12, 3.34],
    ["2025/02", 1.79, 3.36],
    ["2025/03", 2.18, 3.35],
    ["2025/04", 2.05, 3.37],
    ["2025/05", 1.88, 3.36],
    ["2025/06", 1.77, 3.35],
    ["2025/07", 1.92, 3.34],
    ["2025/08", 1.83, 3.35],
    ["2025/09", 1.74, 3.34],
    ["2025/10", 1.58, 3.33],
    ["2025/11", 1.49, 3.32],
    ["2025/12", 1.31, 3.30],

    ["2026/01", 2.66, 3.36],
    ["2026/02", 1.75, 3.33],
    ["2026/03", 1.20, 3.35],
    ["2026/04", 1.74, 3.30],
    ["2026/05", 2.20, 3.27],

]

summaries = {
    "2024/01": "春節帶動消費增加",
    "2024/07": "暑假旅遊需求推升服務價格",
    "2025/08": "電價調整影響 CPI",
    "2026/03": "物價漲幅回落，失業率維持低檔",
    "2026/04": "CPI漲幅擴大，失業率降至低檔",
    "2026/05": "CPI升破2%，失業率續降",
}


def to_ym(value):
    """
    將官方資料的年月轉為 yyyy/mm。
    支援：
    2026/05
    2026-05
    115年5月
    115/05
    11505
    202605
    """
    if value is None:
        return ""

    s = str(value).strip()
    s = s.replace(" ", "")

    # Excel 日期
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y/%m")

    # 2026/05 或 2026-05
    m = re.search(r"(20\d{2})[/-](\d{1,2})", s)
    if m:
        return f"{m.group(1)}/{m.group(2).zfill(2)}"

    # 115年5月
    m = re.search(r"(1\d{2})年(\d{1,2})月", s)
    if m:
        return f"{int(m.group(1)) + 1911}/{m.group(2).zfill(2)}"

    # 115/05
    m = re.search(r"(1\d{2})[/-](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)) + 1911}/{m.group(2).zfill(2)}"

    # 11505
    m = re.fullmatch(r"(1\d{2})(\d{2})", s)
    if m:
        return f"{int(m.group(1)) + 1911}/{m.group(2)}"

    # 202605
    m = re.fullmatch(r"(20\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    return ""


def to_float(value):
    if value is None:
        return None

    s = str(value).strip()
    s = s.replace(",", "")
    s = s.replace("%", "")

    if s in ["", "-", "—", "…", "nan", "None"]:
        return None

    try:
        return round(float(s), 2)
    except Exception:
        return None


def download(url):
    res = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    res.raise_for_status()
    return res.content


def fetch_unemployment_rate():
    """
    讀取政府資料開放平臺 XML：
    年月別_Year_and_month
    總計_Total_百分比
    """
    content = download(UNEMPLOYMENT_XML_URL)
    root = ET.fromstring(content)

    rows = []

    def tag_name(tag):
        return tag.split("}")[-1]

    for elem in root.iter():
        children = list(elem)
        if len(children) < 2:
            continue

        row = {}
        for child in children:
            row[tag_name(child.tag)] = (child.text or "").strip()

        date_key = next((k for k in row.keys() if "年月" in k or "Year_and_month" in k), None)
        total_key = next((k for k in row.keys() if "總計" in k or "Total" in k), None)

        if date_key and total_key:
            ym = to_ym(row.get(date_key))
            rate = to_float(row.get(total_key))

            if ym and rate is not None:
                rows.append({
                    "年月": ym,
                    "失業率": rate
                })

    df = pd.DataFrame(rows).drop_duplicates("年月")
    df = df.sort_values("年月")

    if df.empty:
        raise ValueError("失業率 XML 解析後沒有資料")

    return df


def fetch_cpi_yoy():
    """
    讀取主計總處 CPI Excel。
    這裡使用較寬鬆的方式解析：
    1. 讀取所有工作表
    2. 找出含有年月與年增率的資料列
    3. 轉成 年月 / CPI年增率
    """
    content = download(CPI_EXCEL_URL)

    # .xls 需要 xlrd。GitHub Actions 請安裝 xlrd。
    excel = pd.ExcelFile(io.BytesIO(content), engine="xlrd")

    candidates = []

    for sheet in excel.sheet_names:
        raw = pd.read_excel(
            excel,
            sheet_name=sheet,
            header=None,
            dtype=str
        )

        # 逐列掃描，找出可能的「年月 + CPI 年增率」
        for _, row in raw.iterrows():
            values = [x for x in row.tolist() if str(x).strip() not in ["", "nan", "None"]]

            if len(values) < 2:
                continue

            ym = ""
            ym_index = None

            for idx, value in enumerate(values):
                parsed_ym = to_ym(value)
                if parsed_ym:
                    ym = parsed_ym
                    ym_index = idx
                    break

            if not ym or ym_index is None:
                continue

            # 從該列後面找數字。
            # 官方表格通常同列會有指數、月增率、年增率等數字。
            # 這裡優先取最後一個合理百分比數字作為年增率。
            nums = []
            for value in values[ym_index + 1:]:
                num = to_float(value)
                if num is not None and -20 <= num <= 20:
                    nums.append(num)

            if nums:
                candidates.append({
                    "年月": ym,
                    "CPI年增率": nums[-1]
                })

    df = pd.DataFrame(candidates).drop_duplicates("年月", keep="last")
    df = df.sort_values("年月")

    if df.empty:
        raise ValueError("CPI Excel 解析後沒有資料")

    return df


def build_summary(row):
    ym = row["年月"]

    if ym in summaries:
        return summaries[ym]

    cpi = row.get("CPI年增率")
    unemployment = row.get("失業率")

    if pd.isna(cpi) or pd.isna(unemployment):
        return ""

    if cpi >= 2 and unemployment <= 3.3:
        return "CPI高於2%，失業率維持低檔"
    elif cpi >= 2:
        return "CPI漲幅偏高，需觀察物價壓力"
    elif unemployment <= 3.3:
        return "失業率維持低檔，就業市場相對穩定"
    else:
        return "物價與就業市場維持平穩"


def main():
    fallback_df = pd.DataFrame(
        fallback_data,
        columns=["年月", "CPI年增率", "失業率"]
    )

    cpi_df = pd.DataFrame()
    unemployment_df = pd.DataFrame()

    try:
        cpi_df = fetch_cpi_yoy()
        print(f"CPI 自動抓取成功：{len(cpi_df)} 筆，最新月份 {cpi_df.iloc[-1]['年月']}")
    except Exception as e:
        print(f"CPI 自動抓取失敗，改用保底資料：{e}")

    try:
        unemployment_df = fetch_unemployment_rate()
        print(f"失業率自動抓取成功：{len(unemployment_df)} 筆，最新月份 {unemployment_df.iloc[-1]['年月']}")
    except Exception as e:
        print(f"失業率自動抓取失敗，改用保底資料：{e}")

    if not cpi_df.empty and not unemployment_df.empty:
        df = pd.merge(cpi_df, unemployment_df, on="年月", how="inner")
    else:
        df = fallback_df.copy()

    # 若自動抓到的資料比 fallback 少，補回 fallback，避免畫面少資料
    df = pd.concat([fallback_df, df], ignore_index=True)
    df = df.drop_duplicates("年月", keep="last")
    df = df.sort_values("年月").reset_index(drop=True)

    df["AI摘要"] = df.apply(build_summary, axis=1)

    df["更新時間"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    os.makedirs("data", exist_ok=True)

    df.to_csv(
        "data/taiwan_cpi_unemployment.csv",
        index=False,
        encoding="utf-8-sig"
    )

    df.to_json(
        "data/taiwan_cpi_unemployment.json",
        orient="records",
        force_ascii=False,
        indent=2
    )

    print(df.tail(12))
    print("完成")


if __name__ == "__main__":
    main()
