import requests
from bs4 import BeautifulSoup
import json
import os
import re
import feedparser
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

os.makedirs("data", exist_ok=True)

# =====================================================
# 一、重要公告：政府機關公告自動更新
# =====================================================

SOURCES = [
    {
        "unit": "最新法令動態",
        "url": "https://laws.mol.gov.tw/"
    },
    {
        "unit": "勞動部",
        "url": "https://www.mol.gov.tw/1607/1632/1633/"
    },
    {
        "unit": "勞動力發展署",
        "url": "https://www.wda.gov.tw/News.aspx?n=6&sms=10294"
    },
    {
        "unit": "勞保局",
        "url": "https://www.bli.gov.tw/0100147.html"
    }
]

IGNORE_KEYWORDS = [
    "按Enter到主內容區",
    "按 Enter 到主內容區",
    "Enter到主內容區",
    "Enter 到主內容區",
    "主內容區",
    "網站導覽",
    "回首頁",
    ":::",
    "勞動部勞動法令查詢系統"
]

LAW_KEYWORDS = ["修正", "訂定", "發布", "廢止", "生效", "公告"]

def normalize_date(text):
    text = text.replace("-", "/")

    match = re.search(r"20\d{2}/\d{1,2}/\d{1,2}", text)
    if match:
        y, m, d = match.group().split("/")
        return f"{y}/{m.zfill(2)}/{d.zfill(2)}"

    match = re.search(r"(11[3-9]|12[0-9])/\d{1,2}/\d{1,2}", text)
    if match:
        y, m, d = match.group().split("/")
        return f"{int(y) + 1911}/{m.zfill(2)}/{d.zfill(2)}"

    return ""

def clean_title(title):
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^\d+\s*", "", title)
    title = re.sub(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}", "", title)
    title = re.sub(r"(11[3-9]|12[0-9])[-/]\d{1,2}[-/]\d{1,2}", "", title)
    title = re.sub(r"^[-/]\d{1,2}[-/]\d{1,2}\s*", "", title)
    title = re.sub(r"^頭條\s*", "", title)
    return title.strip()

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
        page_text = soup.get_text(" ", strip=True)

        for a in soup.find_all("a"):
            raw_title = a.get_text(" ", strip=True)
            title_check = raw_title.replace(" ", "")
            href = a.get("href", "")

            if not raw_title or len(raw_title) < 8:
                continue

            if any(k in raw_title for k in IGNORE_KEYWORDS):
                continue

            if any(k in title_check for k in IGNORE_KEYWORDS):
                continue

            if source["unit"] == "最新法令動態":
                if not any(k in raw_title for k in LAW_KEYWORDS):
                    continue

            parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
            search_text = raw_title + " " + parent_text

            if raw_title in page_text:
                pos = page_text.find(raw_title)
                search_text += " " + page_text[pos:pos + 300]

            date = normalize_date(search_text)

            if not date:
                if source["unit"] == "最新法令動態":
                    date = datetime.now().strftime("%Y/%m/%d")
                else:
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

all_gov_news = []

for source in SOURCES:
    news = fetch_news(source)

    news = sorted(
        news,
        key=lambda x: x["日期"],
        reverse=True
    )[:5]

    print(source["unit"], "抓到", len(news), "筆")

    all_gov_news.extend(news)

seen = set()
unique_gov_news = []

for item in all_gov_news:
    key = item["單位"] + item["標題"]

    if key not in seen:
        seen.add(key)
        unique_gov_news.append(item)

with open("data/taiwan_news.json", "w", encoding="utf-8") as f:
    json.dump(unique_gov_news, f, ensure_ascii=False, indent=2)

print("重要公告更新完成")


# =====================================================
# 二、輿情觀察：Google News RSS 自動更新
# =====================================================

major_keywords = [
    "補助", "津貼", "失業", "職災", "工資", "基本工資", "勞基法", "修法",
    "職安", "防護", "退休", "就業", "人才", "缺工", "補貼", "減班",
    "裁員", "裁撤", "資遣", "關廠", "停工", "訓練", "補助申請",
    "重大", "新制", "設廠", "擴廠", "投資", "高階異動",
    "董事長", "總經理", "執行長", "CEO", "接班", "聘任", "離職", "辭職",
    "AI", "半導體", "電動車", "海外併購", "罷工", "調薪", "加薪"
]

general_keywords = [
    "裁員", "裁撤", "資遣", "關廠", "停工", "缺工", "徵才", "招募",
    "職缺", "人力", "人資", "勞動", "勞基法", "工時", "退休", "退休金",
    "加薪", "調薪", "失業", "失業率", "就業", "就業市場", "就業機會",
    "設廠", "擴廠", "投資", "半導體", "AI", "電動車", "罷工",
    "海外併購", "董事長", "總經理", "執行長", "CEO", "高階異動",
    "接班", "聘任", "離職", "辭職"
]

companies = [
    "鴻海", "三星", "台積電", "聯發科", "比亞迪", "特斯拉",
    "和碩", "緯創", "小米", "蘋果", "華碩", "台達電"
]

company_topics = [
    "裁員", "徵才", "缺工", "人力", "AI", "半導體", "電動車",
    "設廠", "擴廠", "投資", "工廠", "海外", "高階異動", "接班"
]

keywords = []
keywords.extend(general_keywords)

for company in companies:
    for topic in company_topics:
        keywords.append(f"{company} {topic}")

rss_urls = [
    "https://news.google.com/rss/search?q=台灣+人資&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+勞工&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+勞基法&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+裁員&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+缺工&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+薪資&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+就業&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+設廠&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+擴廠&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+電動車&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+半導體&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=印度+設廠&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=越南+設廠&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=董事長+異動&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=總經理+接任&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=三星+裁員+AI+半導體&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台積電+設廠+擴廠+人才&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=比亞迪+電動車+設廠+人力&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=特斯拉+裁員+電動車+人力&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=聯發科+半導體+人才+徵才&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=華碩+人力+裁員+AI&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=Digitimes+半導體+AI&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=Inside+科技+AI+人才&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=ABMedia+科技+AI&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=Newtalk+勞工+產業&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=鉅亨網+半導體+電動車+AI&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
]

all_insight_news = []

for rss_url in rss_urls:
    feed = feedparser.parse(rss_url)

    for item in feed.entries:
        title = item.get("title", "")
        link = item.get("link", "")
        source = item.get("source", {}).get("title", "新聞")
        published_raw = item.get("published", "")

        try:
            published = parsedate_to_datetime(published_raw).strftime("%Y/%m/%d")
        except Exception:
            published = datetime.now().strftime("%Y/%m/%d")

        if any(k in title for k in keywords):
            is_major = any(m in title for m in major_keywords)

            all_insight_news.append({
            "日期": published,
            "來源": source,
            "標題": title,
            "連結": link,
            "重要": is_major
    })

old_news = []

try:
    with open("data/insight_news.json", "r", encoding="utf-8") as f:
        old_news = json.load(f)
except Exception:
    old_news = []

all_insight_news.extend(old_news)

unique_insight_news = []
seen_titles = set()

for n in all_insight_news:
    if n["標題"] not in seen_titles:
        seen_titles.add(n["標題"])
        unique_insight_news.append(n)

unique_insight_news.sort(key=lambda x: x["日期"], reverse=True)
unique_insight_news = unique_insight_news[:100]

with open("data/insight_news.json", "w", encoding="utf-8") as f:
    json.dump(unique_insight_news, f, ensure_ascii=False, indent=2)

titles_text = " ".join([n["標題"] for n in unique_insight_news[:20]])

summary = []

if any(k in titles_text for k in ["設廠", "擴廠", "投資", "印度", "越南"]):
    summary.append("近期產業投資、設廠或海外布局消息增加，印度與越南仍是值得關注的區域。")

if any(k in titles_text for k in ["裁員", "裁撤", "關廠", "資遣", "停工"]):
    summary.append("部分企業出現裁員、關廠或人力調整訊號，需留意後續就業市場與勞資風險。")

if any(k in titles_text for k in ["徵才", "招募", "缺工", "職缺", "人力"]):
    summary.append("市場同時出現徵才、缺工與人力需求相關訊息，顯示人才供需仍需持續觀察。")

if any(k in titles_text for k in ["董事長", "總經理", "CEO", "接任", "異動", "聘任"]):
    summary.append("近期有高階主管異動或接班相關新聞，可作為企業治理與組織變動觀察指標。")

if any(k in titles_text for k in ["半導體", "電動車", "AI", "台積電", "三星", "特斯拉"]):
    summary.append("半導體、AI 與電動車相關產業動態仍是本期科技業輿情重點。")

if not summary:
    summary.append("目前已抓取最新 HR 與產業相關新聞，尚未出現明顯集中議題。")

summary_data = {
    "更新時間": datetime.now().strftime("%Y/%m/%d"),
    "摘要": summary
}

with open("data/insight_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary_data, f, ensure_ascii=False, indent=2)

print("輿情觀察更新完成")
print(f"重要公告共 {len(unique_gov_news)} 筆")
print(f"輿情新聞共 {len(unique_insight_news)} 筆")
