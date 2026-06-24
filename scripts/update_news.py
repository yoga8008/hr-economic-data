import requests
from bs4 import BeautifulSoup
import json
import os
import re
import feedparser
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, quote_plus

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

LAW_KEYWORDS = [
    "修正", "訂定", "發布", "廢止", "生效", "公告",
    "修法", "新法", "新制", "上路", "罰則"
]


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

# 重要新聞關鍵字：用來標記「重要」
major_keywords = [
    # 法規／政策
    "補助", "津貼", "勞基法", "修法", "新法", "新制", "上路",
    "勞動部", "法規", "罰則", "公告", "政策",

    # 職場管理風險
    "職場霸凌", "霸凌", "性騷", "申訴", "職災", "職安",
    "防護", "勞資爭議", "罷工",

    # 人力供需
    "失業", "失業率", "青年失業", "就業", "人才", "缺工",
    "移工", "外籍移工", "徵才", "招募", "職缺", "人力",

    # 企業營運異動
    "工資", "基本工資", "退休", "補貼", "減班",
    "裁員", "裁撤", "資遣", "關廠", "停工", "訓練",
    "補助申請", "重大", "設廠", "擴廠", "投資",

    # 高階異動
    "高階異動", "董事長", "總經理", "執行長", "CEO",
    "接班", "聘任", "離職", "辭職",

    # 科技產業
    "AI", "半導體", "電動車", "海外併購", "調薪", "加薪"
]

# 一般新聞關鍵字：用來決定新聞是否收進 insight_news.json
general_keywords = [
    # 職場管理風險
    "職場霸凌", "霸凌", "性騷", "申訴", "職災", "職安",
    "勞資爭議", "罷工",

    # 法規政策
    "勞動", "勞基法", "工時", "修法", "新法", "新制",
    "上路", "勞動部", "法規", "罰則", "政策",

    # 人力供需
    "裁員", "裁撤", "資遣", "關廠", "停工", "缺工",
    "徵才", "招募", "職缺", "人力", "人資",
    "退休", "退休金", "加薪", "調薪",
    "失業", "失業率", "青年失業", "就業", "就業市場",
    "就業機會", "移工", "外籍移工",

    # 企業營運與產業
    "設廠", "擴廠", "投資", "半導體", "AI", "電動車",
    "海外併購",

    # 高階異動
    "董事長", "總經理", "執行長", "CEO", "高階異動",
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


def make_google_news_rss_url(query):
    encoded_query = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


rss_queries = [
    # HR／勞動基本盤
    "台灣 人資",
    "台灣 勞工",
    "台灣 勞基法",
    "台灣 裁員",
    "台灣 缺工",
    "台灣 薪資",
    "台灣 就業",

    # 新增：職場管理與法規風險
    "台灣 職場霸凌",
    "台灣 霸凌 勞動部",
    "台灣 勞動法 新法",
    "台灣 勞動新制 上路",
    "台灣 勞資爭議",
    "台灣 職災",
    "台灣 性騷 申訴",
    "台灣 移工",
    "台灣 青年失業",

    # 產業營運
    "台灣 設廠",
    "台灣 擴廠",
    "台灣 電動車",
    "台灣 半導體",
    "印度 設廠",
    "越南 設廠",

    # 高階異動
    "董事長 異動",
    "總經理 接任",

    # 企業／產業指定
    "三星 裁員 AI 半導體",
    "台積電 設廠 擴廠 人才",
    "比亞迪 電動車 設廠 人力",
    "特斯拉 裁員 電動車 人力",
    "聯發科 半導體 人才 徵才",
    "華碩 人力 裁員 AI",

    # 科技媒體與財經媒體
    "Digitimes 半導體 AI",
    "Inside 科技 AI 人才",
    "ABMedia 科技 AI",
    "Newtalk 勞工 產業",
    "鉅亨網 半導體 電動車 AI"
]

rss_urls = [make_google_news_rss_url(q) for q in rss_queries]

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


# =====================================================
# 三、AI 今日重點摘要：改為高風險與 HR 優先
# =====================================================

def clean_news_headline(title):
    """
    Google News 標題常見格式：
    標題 - 媒體名稱
    這裡只保留前面的新聞標題，讓摘要更清楚。
    """
    title = re.sub(r"\s+-\s+.+$", "", title).strip()
    return title


def shorten(text, max_len=42):
    if not text:
        return ""
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def has_any(text, words):
    return any(k in text for k in words)


def pick_title(titles, words):
    for title in titles:
        if any(k in title for k in words):
            return shorten(clean_news_headline(title))
    return ""


recent_titles = [n["標題"] for n in unique_insight_news[:50]]
titles_text = " ".join(recent_titles)

summary = []

# 關鍵字群組
bullying_words = ["職場霸凌", "霸凌"]
law_words = ["新法", "修法", "上路", "勞動部", "罰則", "法規", "新制", "政策"]
workplace_risk_words = ["性騷", "申訴", "職災", "勞資爭議", "罷工", "職安"]
labor_supply_words = ["缺工", "移工", "外籍移工", "徵才", "招募", "職缺", "人力"]
employment_words = ["失業率", "青年失業", "失業", "就業市場", "就業機會"]
layoff_words = ["裁員", "裁撤", "關廠", "資遣", "停工", "減班"]
investment_words = ["設廠", "擴廠", "投資", "印度", "越南", "海外"]
tech_words = ["半導體", "電動車", "AI", "台積電", "三星", "特斯拉", "先進封裝"]
executive_words = ["董事長", "總經理", "CEO", "接任", "異動", "聘任", "高階異動"]

# 1. 職場霸凌／法規：最高優先
bullying_hit = has_any(titles_text, bullying_words)
law_hit = has_any(titles_text, law_words)

if bullying_hit and law_hit:
    title = pick_title(recent_titles, bullying_words + law_words)
    if title:
        summary.append(
            f"職場霸凌與勞動法規議題為今日高優先輿情，代表新聞為「{title}」，企業應關注申訴處理、調查流程、主管管理責任及內部制度調整。"
        )
    else:
        summary.append(
            "職場霸凌與勞動法規議題為今日高優先輿情，企業應關注申訴處理、調查流程、主管管理責任及內部制度調整。"
        )

elif bullying_hit:
    title = pick_title(recent_titles, bullying_words)
    if title:
        summary.append(
            f"今日出現職場霸凌相關新聞，代表新聞為「{title}」，企業應留意員工關係、申訴管道與管理責任。"
        )
    else:
        summary.append(
            "今日出現職場霸凌相關新聞，企業應留意員工關係、申訴管道與管理責任。"
        )

elif law_hit:
    title = pick_title(recent_titles, law_words)
    if title:
        summary.append(
            f"今日新聞涉及勞動法規或政策變動，代表新聞為「{title}」，建議持續追蹤對公司人資制度、內部管理與法遵作業的影響。"
        )
    else:
        summary.append(
            "今日新聞涉及勞動法規或政策變動，建議持續追蹤對公司人資制度、內部管理與法遵作業的影響。"
        )

# 2. 職場管理風險
if has_any(titles_text, workplace_risk_words):
    title = pick_title(recent_titles, workplace_risk_words)
    if title:
        summary.append(
            f"職場管理風險相關新聞增加，代表新聞為「{title}」，需留意申訴、職災、勞資爭議或罷工等後續風險。"
        )
    else:
        summary.append(
            "職場管理風險相關新聞增加，需留意申訴、職災、勞資爭議或罷工等後續風險。"
        )

# 3. 人力供需風險
if has_any(titles_text, labor_supply_words):
    title = pick_title(recent_titles, labor_supply_words)
    if title:
        summary.append(
            f"缺工、移工與徵才相關議題持續受到關注，代表新聞為「{title}」，顯示基層人力供需與招募穩定性仍需觀察。"
        )
    else:
        summary.append(
            "缺工、移工與徵才相關議題持續受到關注，顯示基層人力供需與招募穩定性仍需觀察。"
        )

if has_any(titles_text, employment_words):
    title = pick_title(recent_titles, employment_words)
    if title:
        summary.append(
            f"就業市場相關數據受到關注，代表新聞為「{title}」，青年失業與整體人才供需狀況仍是後續觀察重點。"
        )
    else:
        summary.append(
            "就業市場相關數據受到關注，青年失業與整體人才供需狀況仍是後續觀察重點。"
        )

# 4. 企業營運異動
if has_any(titles_text, layoff_words):
    title = pick_title(recent_titles, layoff_words)
    if title:
        summary.append(
            f"部分企業出現裁員、關廠或人力調整訊號，代表新聞為「{title}」，需留意後續就業市場變化與勞資風險。"
        )
    else:
        summary.append(
            "部分企業出現裁員、關廠或人力調整訊號，需留意後續就業市場變化與勞資風險。"
        )

if has_any(titles_text, investment_words):
    title = pick_title(recent_titles, investment_words)
    if title:
        summary.append(
            f"投資、設廠或海外布局仍有相關消息，代表新聞為「{title}」，印度、越南等區域可持續作為產業與人力需求觀察重點。"
        )
    else:
        summary.append(
            "投資、設廠或海外布局仍有相關消息，印度、越南等區域可持續作為產業與人力需求觀察重點。"
        )

# 5. 科技產業趨勢
if has_any(titles_text, tech_words):
    title = pick_title(recent_titles, tech_words)
    if title:
        summary.append(
            f"半導體、AI 與電動車相關產業動態仍是科技業輿情重點，代表新聞為「{title}」，後續可觀察對人才需求與組織配置的影響。"
        )
    else:
        summary.append(
            "半導體、AI 與電動車相關產業動態仍是科技業輿情重點，後續可觀察對人才需求與組織配置的影響。"
        )

# 6. 高階異動
if has_any(titles_text, executive_words):
    title = pick_title(recent_titles, executive_words)
    if title:
        summary.append(
            f"近期有高階主管異動或接班相關新聞，代表新聞為「{title}」，可作為企業治理與組織變動觀察指標。"
        )
    else:
        summary.append(
            "近期有高階主管異動或接班相關新聞，可作為企業治理與組織變動觀察指標。"
        )

if not summary:
    summary.append("目前已抓取最新 HR 與產業相關新聞，尚未出現明顯集中或高風險議題。")

# 最多顯示 5 點，避免摘要過長
summary = summary[:5]

summary_data = {
    "更新時間": datetime.now().strftime("%Y/%m/%d"),
    "摘要": summary
}

with open("data/insight_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary_data, f, ensure_ascii=False, indent=2)

print("輿情觀察更新完成")
print(f"重要公告共 {len(unique_gov_news)} 筆")
print(f"輿情新聞共 {len(unique_insight_news)} 筆")
