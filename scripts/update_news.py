import feedparser
import json
from datetime import datetime
from email.utils import parsedate_to_datetime

# 重大新聞關鍵字
major_keywords = [
    "補助", "津貼", "失業", "職災", "工資", "基本工資", "勞基法", "修法",
    "職安", "防護", "退休", "就業", "人才", "缺工", "補貼", "減班",
    "裁員", "裁撤", "資遣", "關廠", "停工", "訓練", "補助申請",
    "重大", "新制", "設廠", "擴廠", "投資", "高階異動",
    "董事長", "總經理", "執行長", "CEO", "接班", "聘任", "離職", "辭職",
    "AI", "半導體", "電動車", "海外併購", "罷工", "調薪", "加薪"
]

# 通用 HR / 經濟 / 產業關鍵字
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

all_news = []

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

        if (
            any(k in title for k in keywords)
            and any(m in title for m in major_keywords)
        ):
            all_news.append({
                "日期": published,
                "來源": source,
                "標題": title,
                "連結": link
            })

# 讀取舊資料
old_news = []

try:
    with open("data/insight_news.json", "r", encoding="utf-8") as f:
        old_news = json.load(f)
except Exception:
    old_news = []

# 新舊合併
all_news.extend(old_news)

# 去重複
unique_news = []
seen_titles = set()

for n in all_news:
    if n["標題"] not in seen_titles:
        seen_titles.add(n["標題"])
        unique_news.append(n)

# 日期排序（最新在前）
unique_news.sort(key=lambda x: x["日期"], reverse=True)

# 保留最新100筆
unique_news = unique_news[:100]

with open("data/insight_news.json", "w", encoding="utf-8") as f:
    json.dump(unique_news, f, ensure_ascii=False, indent=2)

# AI摘要
titles_text = " ".join([n["標題"] for n in unique_news[:20]])

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

print(f"完成，共 {len(unique_news)} 筆新聞")
