import feedparser
import json
from datetime import datetime

keywords = [

    # 投資 / 設廠 / 人力
    "投資",
    "設廠",
    "擴廠",
    "關廠",
    "人力",
    "徵才",
    "招募",
    "缺工",
    "挖角",
    "就業機會",

    # 人力增減 / 裁員
    "裁員",
    "裁撤",
    "資遣",
    "減產",
    "停工",
    "關廠",

    # 高階異動
    "高階異動",
    "高層",
    "異動",
    "接任",
    "調動",
    "交接",
    "接班",
    "二代",
    "董事長",
    "總經理",
    "執行長",
    "CEO",
    "出任",
    "聘任",

    # 離退
    "退休",
    "辭世",
    "解任",
    "辭職",
    "離職",

    # 勞動 / 法規
    "工時",
    "加班",
    "勞基法",
    "退休金",
    "最低工資",
    "基本工資",
    "薪資",
    "加薪",
    "調薪",
    "失業",
    "失業率",
    "就業率",
    "罷工",

    # HR / 勞動市場
    "職缺",
    "勞動",
    "人資",
    "勞動法令",
    "就業市場",

    # 產業
    "半導體",
    "電動車",
    "AI",

    # 海外布局
    "印度",
    "越南",

    # 財務 / 風險
    "破產",
    "併購",
    "海外併購",

    # 鴻海競爭對手
    "台達電",
    "三星",
    "小米",
    "緯創",
    "蘋果",
    "和碩",
    "比亞迪",
    "特斯拉",
    "台積電",
    "聯發科",
    "華碩"
]

rss_urls = [
    "https://news.google.com/rss/search?q=Digitimes&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=Inside+科技&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=ABMedia&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=Newtalk&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=鉅亨網&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
]

all_news = []

for rss_url in rss_urls:

    feed = feedparser.parse(rss_url)

    for item in feed.entries:

        title = item.title

        if any(k in title for k in keywords):

            news = {
                "日期": item.published,
                "來源": item.source.title if hasattr(item, "source") else "新聞",
                "標題": title,
                "連結": item.link
            }

            all_news.append(news)

# 去重複
unique_news = []
titles = set()

for n in all_news:
    if n["標題"] not in titles:
        titles.add(n["標題"])
        unique_news.append(n)

# 最新20筆
unique_news = unique_news[:20]

with open("data/insight_news.json", "w", encoding="utf-8") as f:
    json.dump(unique_news, f, ensure_ascii=False, indent=2)

print(f"完成，共 {len(unique_news)} 筆新聞")
