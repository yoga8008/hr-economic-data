import requests
from bs4 import BeautifulSoup
import json
import os
import re
from urllib.parse import urljoin

SOURCES = [
    {"unit": "勞動部", "url": "https://www.mol.gov.tw/1607/1632/1633/"},
    {"unit": "勞動力發展署", "url": "https://www.wda.gov.tw/News.aspx?n=6&sms=10294"},
    {"unit": "健保署", "url": "https://www.nhi.gov.tw/ch/lp-3255-1.html"}
]

IGNORE_KEYWORDS = ["按Enter到主內容區", "Enter到主內容區", "主內容區", "網站導覽", "回首頁", ":::"]

def normalize_date(text):
    text = text.replace("-", "/")

    m = re.search(r"20\d{2}/\d{1,2}/\d{1,2}", text)
    if m:
        y, mo, d = m.group().split("/")
        return f"{y}/{mo.zfill(2)}/{d.zfill(2)}"

    m = re.search(r"(?<!\d)(11[3-9]|12[0-9])/\d{1,2}/\d{1,2}", text)
    if m:
        y, mo, d = m.group().split("/")
        return f"{int(y)+1911}/{mo.zfill(2)}/{d.zfill(2)}"

    return ""

def clean_title(title):
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^\d+\s*", "", title)
    title = re.sub(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}", "", title)
    title = re.sub(r"(11[3-9]|12[0-9])[-/]\d{1,2}[-/]\d{1,2}", "", title)
    return title.strip()

def fetch_news(source):
    items = []

    try:
        res = requests.get(source["url"], timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        page_text = soup.get_text(" ", strip=True)

        for a in soup.find_all("a"):
            raw_title = a.get_text(" ", strip=True)
            title_check = raw_title.replace(" ", "")
            href = a.get("href", "")

            if not raw_title or len(raw_title) < 8:
                continue

            if any(k in title_check for k in IGNORE_KEYWORDS):
                continue

            parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""

            # 重點：同時看 title + parent + 附近文字
            search_text = raw_title + " " + parent_text

            if raw_title in page_text:
                pos = page_text.find(raw_title)
                search_text += " " + page_text[pos:pos + 300]

            date = normalize_date(search_text)

            if not date:
                continue

            title = clean_title(raw_title)

            if not title or len(title) < 8:
                continue

            items.append({
                "日期": date,
                "單位": source["unit"],
                "標題": title,
                "連結": urljoin(source["url"], href)
            })

    except Exception as e:
        print(f"抓取失敗：{source['unit']} {e}")

    return items

all_news = []

for source in SOURCES:
    news = fetch_news(source)
    news = sorted(news, key=lambda x: x["日期"], reverse=True)[:5]
    print(source["unit"], "抓到", len(news), "筆")
    all_news.extend(news)

seen = set()
unique_news = []

for item in all_news:
    key = item["單位"] + item["標題"]
    if key not in seen:
        seen.add(key)
        unique_news.append(item)

os.makedirs("data", exist_ok=True)

with open("data/taiwan_news.json", "w", encoding="utf-8") as f:
    json.dump(unique_news, f, ensure_ascii=False, indent=2)

print("公告更新完成")
print(json.dumps(unique_news, ensure_ascii=False, indent=2))
