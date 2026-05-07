import feedparser
import json
from datetime import datetime

keywords = [
    "勞基法",
    "工時",
    "加班",
    "薪資",
    "基本工資",
    "最低工資",
    "裁員",
    "資遣",
    "缺工",
    "徵才",
    "招募",
    "AI",
    "就業",
    "勞保",
    "健保",
    "退休"
]

rss_urls = [
    "https://news.google.com/rss/search?q=台灣+人資&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+勞工&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q=台灣+薪資&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
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
