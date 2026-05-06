import requests
from bs4 import BeautifulSoup
import json
import os
import re
from urllib.parse import urljoin

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

IGNORE_KEYWORDS = ["Enter", "主內容區", "網站導覽", "回首頁", "搜尋", ":::"]

def normalize_date(text):
    text = text.replace("-", "/")
    m = re.search(r"(11[3-9]|12[0-9])/\d{1,2}/\d{1,2}", text)
    if m:
        y, mo, d = m.group().split("/")
        return f"{int(y)+1911}/{mo.zfill(2)}/{d.zfill(2)}"
    return ""

def fetch_news(source):
    items = []

    res = requests.get(source["url"], timeout=20, headers={"User-Agent":"Mozilla/5.0"})
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    for a in soup.find_all("a"):
        title = a.get_text(" ", strip=True)
        href = a.get("href", "")

        if not title or len(title) < 8:
            continue
        if any(k in title for k in IGNORE_KEYWORDS):
            continue

        block = a.find_parent()
        block_text = block.get_text(" ", strip=True) if block else title
        date = normalize_date(block_text + " " + title)

        if not date:
            continue

        items.append({
            "日期": date,
            "單位": source["unit"],
            "標題": title,
            "連結": urljoin(source["url"], href)
        })

    return items

all_news = []

for source in SOURCES:
    try:
        result = fetch_news(source)
        print(source["unit"], "抓到", len(result), "筆")
        all_news.extend(result)
    except Exception as e:
        print(source["unit"], "抓取失敗", e)

seen = set()
unique_news = []

for item in all_news:
    key = item["單位"] + item["標題"]
    if key not in seen:
        seen.add(key)
        unique_news.append(item)

unique_news = sorted(unique_news, key=lambda x: x["日期"], reverse=True)

os.makedirs("data", exist_ok=True)

with open("data/taiwan_news.json", "w", encoding="utf-8") as f:
    json.dump(unique_news, f, ensure_ascii=False, indent=2)

print("公告更新完成，共", len(unique_news), "筆")
print(json.dumps(unique_news[:15], ensure_ascii=False, indent=2))
