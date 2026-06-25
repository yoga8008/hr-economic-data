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
# 三、AI 今日重點摘要：HR 風險優先短版
# =====================================================

def has_any(text, words):
    return any(word in text for word in words)


def find_items(news, words, limit=3):
    matched = []

    for item in news:
        title = item.get("標題", "")
        if has_any(title, words):
            matched.append(item)

    return matched[:limit]


def add_summary(summary_list, label, items, message):
    """
    統一摘要格式：
    【主題】今日出現X則相關訊號，後面接 HR 觀察重點。
    不帶代表新聞標題，避免摘要過長。
    """
    if not items:
        return

    count_text = f"{len(items)}則" if len(items) > 1 else "1則"

    summary_list.append(
        f"【{label}】今日出現{count_text}相關訊號，{message}"
    )


# 優先看最新日期，避免舊新聞混入今日摘要
latest_date = unique_insight_news[0]["日期"] if unique_insight_news else datetime.now().strftime("%Y/%m/%d")

today_news = [
    n for n in unique_insight_news
    if n.get("日期") == latest_date
]

# 若最新日期新聞太少，才補最近資料，避免摘要空白
if len(today_news) < 5:
    today_news = unique_insight_news[:30]


risk_categories = [
    {
        "label": "勞動法規與政策變動",
        "words": [
            "新法", "修法", "新制", "上路", "勞動部", "法規",
            "罰則", "勞基法", "職場霸凌防治", "防治法", "政策"
        ],
        "message": "建議優先確認是否涉及公司內規、申訴流程、主管管理責任或法遵作業調整。"
    },
    {
        "label": "職場管理風險",
        "words": [
            "職場霸凌", "霸凌", "性騷", "申訴", "職災",
            "職安", "勞資爭議", "罷工"
        ],
        "message": "需留意員工關係、申訴處理、調查機制及現場管理風險。"
    },
    {
        "label": "人力供需與缺工",
        "words": [
            "缺工", "移工", "外籍移工", "徵才", "招募",
            "職缺", "人力", "人才"
        ],
        "message": "反映基層人力、招募穩定性與用工供給仍需持續觀察。"
    },
    {
        "label": "就業市場變化",
        "words": [
            "失業", "失業率", "青年失業", "就業市場",
            "就業機會", "薪資", "加薪", "調薪"
        ],
        "message": "可作為人才市場溫度、薪資競爭與招募策略調整的參考。"
    },
    {
        "label": "企業人力調整",
        "words": [
            "裁員", "裁撤", "資遣", "關廠", "停工",
            "減班", "離職", "辭職"
        ],
        "message": "需關注後續是否擴大為產業性人力調整或勞資爭議。"
    },
    {
        "label": "高階主管與組織異動",
        "words": [
            "董事長", "總經理", "執行長", "CEO",
            "接班", "聘任", "高階異動", "異動"
        ],
        "message": "可作為企業治理、組織調整與經營方向變化的觀察訊號。"
    },
    {
        "label": "產業投資與海外布局",
        "words": [
            "設廠", "擴廠", "投資", "印度", "越南",
            "海外", "併購"
        ],
        "message": "後續可觀察對區域人力需求、派駐支援與招募量能的影響。"
    },
    {
        "label": "科技產業動態",
        "words": [
            "半導體", "AI", "電動車", "台積電", "三星",
            "特斯拉", "先進封裝", "供應鏈"
        ],
        "message": "可觀察對人才需求、技能配置與組織資源分配的影響。"
    }
]

summary = []
used_labels = set()

for category in risk_categories:
    matched_items = find_items(today_news, category["words"], limit=3)

    if matched_items and category["label"] not in used_labels:
        add_summary(
            summary,
            category["label"],
            matched_items,
            category["message"]
        )
        used_labels.add(category["label"])

    if len(summary) >= 5:
        break

if not summary:
    summary.append(
        "【今日輿情概況】今日已更新 HR 與產業相關新聞，目前未出現高度集中或高風險勞動議題。"
    )

summary_data = {
    "更新時間": latest_date,
    "摘要": summary[:5]
}

with open("data/insight_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary_data, f, ensure_ascii=False, indent=2)

print("輿情觀察更新完成")
print(f"重要公告共 {len(unique_gov_news)} 筆")
print(f"輿情新聞共 {len(unique_insight_news)} 筆")
