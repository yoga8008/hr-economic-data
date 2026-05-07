import feedparser
import json

rss_url = "RSS網址"

feed = feedparser.parse(rss_url)

news = []

for item in feed.entries[:20]:
    news.append({
        "日期": item.published,
        "來源": "勞動部",
        "標題": item.title,
        "連結": item.link
    })

with open("data/insight_news.json","w",encoding="utf-8") as f:
    json.dump(news,f,ensure_ascii=False,indent=2)
