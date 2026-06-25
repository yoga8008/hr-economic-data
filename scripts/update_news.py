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
# 三、AI 今日重點摘要：事件標題＋深度 HR 觀察
# =====================================================

def has_any(text, words):
    return any(word in text for word in words)


def find_items(news, words, limit=5):
    matched = []

    for item in news:
        title = item.get("標題", "")
        if has_any(title, words):
            matched.append(item)

    return matched[:limit]


def add_summary(summary_list, title, items, description):
    """
    摘要格式：
    {
        "標題": "事件標題",
        "說明": "HR觀察說明"
    }

    不放代表新聞標題，避免太長。
    但會依新聞關鍵字判斷是否產生該摘要。
    """
    if not items:
        return

    summary_list.append({
        "標題": title,
        "說明": description
    })


def get_latest_labor_market_text():
    """
    從 update_data.py 產出的 taiwan_cpi_unemployment.json 讀取最新失業率。
    若讀不到，不影響 GitHub Actions，改用一般文字。
    """
    try:
        with open("data/taiwan_cpi_unemployment.json", "r", encoding="utf-8") as f:
            monthly_data = json.load(f)

        if not monthly_data:
            return "整體失業率雖維持低檔，但青年族群就業壓力仍需持續觀察。"

        latest = monthly_data[-1]
        ym = latest.get("年月", "")
        unemployment = latest.get("失業率", "")

        if ym and unemployment != "":
            month_text = ym.split("/")[-1].lstrip("0")
            return f"{month_text}月整體失業率為 {unemployment}%，雖仍屬低檔，但青年族群就業壓力仍需持續觀察。"

    except Exception:
        pass

    return "整體失業率雖維持低檔，但青年族群就業壓力仍需持續觀察。"


# 優先看最新日期，避免舊新聞混入今日摘要
latest_date = unique_insight_news[0]["日期"] if unique_insight_news else datetime.now().strftime("%Y/%m/%d")

today_news = [
    n for n in unique_insight_news
    if n.get("日期") == latest_date
]

# 若最新日期新聞太少，補最近資料，避免摘要空白
if len(today_news) < 5:
    today_news = unique_insight_news[:30]

titles_text = " ".join([n.get("標題", "") for n in today_news])

summary = []


# 1. 職場霸凌 / 勞動新法
bullying_words = ["職場霸凌", "霸凌"]
law_words = ["新法", "修法", "新制", "上路", "勞動部", "法規", "罰則", "防治", "政策"]
bullying_items = find_items(today_news, bullying_words + law_words)

if has_any(titles_text, bullying_words) and has_any(titles_text, law_words):
    add_summary(
        summary,
        "職場霸凌防治新法即將上路",
        bullying_items,
        "職場霸凌議題將從個案處理提升為企業管理與法遵責任。HR需檢查申訴入口是否清楚、受理與調查流程是否有紀錄、保密與防報復機制是否完整；主管端也應補強日常管理、衝突處理與言行界線教育，避免申訴案件擴大為勞檢、訴訟或雇主品牌風險。"
    )
elif has_any(titles_text, bullying_words):
    add_summary(
        summary,
        "職場霸凌議題受到關注",
        bullying_items,
        "相關新聞反映員工關係與現場管理風險升高。企業不能只等申訴發生後才處理，應回頭檢視主管管理方式、員工反映管道、調查紀錄保存及跨部門處理機制，降低事件升級為勞資爭議或外部輿情的可能。"
    )
elif has_any(titles_text, law_words):
    add_summary(
        summary,
        "勞動法規與政策變動需持續追蹤",
        bullying_items,
        "近期勞動政策或法規變動可能影響公司內規、表單、公告及主管管理責任。HR應先判斷是否涉及員工手冊、申訴流程、考勤假別、薪資福利或職安管理，並確認是否需要同步調整內部制度與教育宣導。"
    )


# 2. 青年失業 / 就業市場
employment_words = ["青年失業", "失業率", "失業", "就業市場", "就業機會", "新鮮人", "畢業生"]
employment_items = find_items(today_news, employment_words)

if employment_items:
    add_summary(
        summary,
        "青年失業率仍偏高",
        employment_items,
        get_latest_labor_market_text() + "企業可從校園徵才、實習轉正、基層職缺訓練與留任設計切入，提前布局年輕人才供給，並觀察新鮮人起薪與職能落差是否影響招募競爭力。"
    )


# 3. 缺工 / 移工 / 基層人力
labor_supply_words = [
    "缺工", "移工", "外籍移工", "農業缺工", "人力短缺",
    "徵才", "招募", "職缺", "人力", "基層人力"
]
labor_supply_items = find_items(today_news, labor_supply_words)

if labor_supply_items:
    add_summary(
        summary,
        "缺工與移工議題持續發酵",
        labor_supply_items,
        "缺工與移工新聞反映部分產業基層人力供給仍不穩定，尤其是製造、農業、服務及輪班型工作。HR除觀察招募量能外，也需同步檢視薪資競爭力、住宿交通、工時安排及派遣／移工補充機制，避免缺工影響營運排程與現場管理負荷。"
    )


# 4. 職場管理風險
workplace_risk_words = [
    "性騷", "申訴", "職災", "職安", "勞資爭議", "罷工", "工安", "職業安全"
]
workplace_risk_items = find_items(today_news, workplace_risk_words)

if workplace_risk_items:
    add_summary(
        summary,
        "職場管理與勞資風險需留意",
        workplace_risk_items,
        "申訴、職災、職安或勞資爭議通常不是單一事件，而是現場管理、溝通紀錄與制度落實程度的壓力測試。企業應關注案件是否有明確責任分工、處理時程、佐證資料與員工溝通紀錄，避免後續衍生裁罰、爭議調解或媒體風險。"
    )


# 5. 裁員 / 資遣 / 關廠
layoff_words = ["裁員", "裁撤", "資遣", "關廠", "停工", "減班", "人力調整", "組織調整"]
layoff_items = find_items(today_news, layoff_words)

if layoff_items:
    add_summary(
        summary,
        "企業人力調整訊號值得觀察",
        layoff_items,
        "裁員、資遣、關廠或減班消息可能反映個別企業營運壓力，也可能擴散為產業性人力調整。HR可觀察是否集中於特定產業、地區或職類，並提前檢視內部人力配置、轉調機制、PIP紀錄與資遣流程合規性，避免處理時程不足造成爭議。"
    )


# 6. 半導體 / AI / 電動車
tech_words = [
    "半導體", "AI", "電動車", "台積電", "三星",
    "特斯拉", "先進封裝", "供應鏈", "晶片", "伺服器"
]
tech_items = find_items(today_news, tech_words)

if tech_items:
    add_summary(
        summary,
        "半導體、AI 與電動車仍為產業觀察重點",
        tech_items,
        "半導體、AI與電動車新聞不只代表產業熱度，也會影響人才需求、技能結構與薪資競爭。後續可觀察是否帶動研發、製程、設備、資料分析及海外據點人才需求增加，並評估內部招募、培訓與留才策略是否需要提前調整。"
    )


# 7. 投資 / 設廠 / 海外布局
investment_words = ["設廠", "擴廠", "投資", "印度", "越南", "海外", "併購", "建廠", "布局"]
investment_items = find_items(today_news, investment_words)

if investment_items:
    add_summary(
        summary,
        "產業投資與海外布局持續推進",
        investment_items,
        "企業投資、設廠或海外布局通常會帶動當地招募、派駐支援、薪資行情與管理制度建置需求。HR應觀察投資區域是否與公司布局重疊，並提前評估當地勞動法規、招募難度、外派管理及跨國薪酬福利設計。"
    )


# 8. 高階主管 / 組織異動
executive_words = [
    "董事長", "總經理", "執行長", "CEO",
    "接班", "聘任", "高階異動", "異動", "人事異動"
]
executive_items = find_items(today_news, executive_words)

if executive_items:
    add_summary(
        summary,
        "高階主管與組織異動值得關注",
        executive_items,
        "高階主管異動通常代表經營方向、組織權責或策略重點可能調整。HR可觀察是否伴隨組織重整、事業轉型、成本控管或人才更替訊號，作為後續人力配置、接班計畫與關鍵人才風險評估的參考。"
    )


if not summary:
    summary.append({
        "標題": "今日未出現高度集中風險議題",
        "說明": "目前已更新 HR 與產業相關新聞，尚未觀察到明顯集中或高風險勞動議題。仍建議持續追蹤勞動法規、就業市場、缺工與科技產業動態，作為人資制度與人力配置的背景觀察。"
    })


# 最多顯示 4 點，避免首頁太長
summary = summary[:4]

summary_data = {
    "更新時間": latest_date,
    "摘要": summary
}

with open("data/insight_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary_data, f, ensure_ascii=False, indent=2)

print("輿情觀察更新完成")
print(f"重要公告共 {len(unique_gov_news)} 筆")
print(f"輿情新聞共 {len(unique_insight_news)} 筆")
