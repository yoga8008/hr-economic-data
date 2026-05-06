import pandas as pd
from datetime import datetime

# 模擬資料
data = [
    ["2024/01", 2.43, 3.31],
    ["2024/02", 3.08, 3.39],
    ["2024/03", 2.14, 3.38],
]

df = pd.DataFrame(data, columns=["年月", "CPI年增率", "失業率"])

df["更新時間"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 建立 data 資料夾
import os
os.makedirs("data", exist_ok=True)

# 輸出 CSV
df.to_csv(
    "data/taiwan_cpi_unemployment.csv",
    index=False,
    encoding="utf-8-sig"
)

# 輸出 JSON
df.to_json(
    "data/taiwan_cpi_unemployment.json",
    orient="records",
    force_ascii=False,
    indent=2
)

print(df)
print("完成")
