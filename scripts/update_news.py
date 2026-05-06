import requests
from bs4 import BeautifulSoup
import json
import os
import re

SOURCES = [
    {
        "unit": "勞動部",
        "url": "https://www.mol.gov.tw/1607/1632/1633/"
    },
    {
        "unit": "勞動力發展署",
        "url": "https://www.wda.gov.tw/News.aspx?n=6&sms=10294"
    },
    {
        "unit": "健保署",
        "url": "https://www.nhi.gov.tw/ch/lp-3255-1.html"
    }
]

IGNORE_KEYWORDS = [
    "Enter",
    "主內容區",
    "跳到",
    "網站導覽",
    "回首頁",
    ":::",
    "搜尋",
    "按 Enter"
]

def roc_to_ad(date_text):
    parts = date_text.replace("-", "/").split("/")
    if len(parts) == 3 and len(parts[0]) == 3:
        year = int(parts[0]) + 1911
        return f"{year}/{parts[1].zfill(2)}/{parts[2].zfill(2)}"
    return ""

def valid_date(date):
    try:
        year = int(date.split("/")[0])
        return 2024 <= year <= 2026
    except:
        return False

def fetch_news(source):
    items = []

    try:
        res = requests.get(
            source["url"],
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        res.encoding = "utf-8"

        soup = BeautifulSoup(res.text, "html.parser")

        for a in soup.find_all("a"):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")

            if not title or len(title) < 8:
                continue

            if any(k in title for k in IGNORE_KEYWORDS):
                continue

            parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""

            match = re.search(r"\d{3}[-/]\d{2}[-/]\d{2}", parent_text)

            if not match:
                continue

            date = roc_to_ad(match.group())

            if not valid_date(date):
                continue

            if href.startswith("/"):
                base = source["url"].split("/")[0] + "//" + source["url"].split("/")[2]
                href = base + href
            elif not href.startswith("http"):
                base = "/".join(source["url"].split("/")[:3])
                href = base + "/" + href

            items.append({
                "日期": date,
                "單位": source["unit"],
                "標題": title,
                "連結": href
            })

    except Exception as e:
        print(f"抓取失敗：{source['unit']} {e}")

    return items

all_news = []

for source in SOURCES:
    all_news.extend(fetch_news(source))

seen = set()
unique_news = []

for item in all_news:
    key = item["單位"] + item["標題"]
    if key not in seen:
        seen.add(key)
        unique_news.append(item)

unique_news = sorted(
    unique_news,
    key=lambda x: x["日期"],
    reverse=True
)

os.makedirs("data", exist_ok=True)

with open("data/taiwan_news.json", "w", encoding="utf-8") as f:
    json.dump(unique_news, f, ensure_ascii=False, indent=2)

print("公告更新完成")
print(json.dumps(unique_news[:15], ensure_ascii=False, indent=2))
