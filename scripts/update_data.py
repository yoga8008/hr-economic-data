import pandas as pd
from datetime import datetime

data = [
    ["2024/01", 2.43, 3.31],
    ["2024/02", 3.08, 3.39],
    ["2024/03", 2.14, 3.38],
]

df = pd.DataFrame(data, columns=["年月", "CPI年增率", "失業率"])

df["更新時間"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

df.to_csv("taiwan_cpi_unemployment.csv", index=False, encoding="utf-8-sig")

print("完成")
