"""临时端点传输方式探测脚本：每个端点分别用 query 模式 / body 模式调用（验证后删除）。

body 模式 = 业务参数走 JSON body + 签名覆盖 JSON 序列化业务参数 + 鉴权参数走 query。
"""

import json
import os
import time

import httpx
from datetime import date, timedelta

from governance_lingxing_mcp.auth import LingXingAuth
from governance_lingxing_mcp.config import LXConfig
from governance_lingxing_mcp.signing import sign_request

config = LXConfig.from_env()
token = LingXingAuth(config).get_access_token()
BASE = config.api_base
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
D7 = (date.today() - timedelta(days=7)).isoformat()
MONTH = date.today().strftime("%Y-%m")
ASIN = "B0DQ87Y1P4"  # 真实 ASIN（从 asinList 验证获得）

ENDPOINTS = [
    ("POST", "/bd/profit/report/open/report/asin/list",
     {"sids": [8074], "startDate": D7, "endDate": YESTERDAY, "offset": 0, "length": 2}),
    ("POST", "/bd/goal/management/open/store/batchSelect", {"assessYear": "2026"}),
    ("POST", "/basicOpen/salesAnalysis/productPerformance/performanceTrendByHour",
     {"sids": "8074", "date_start": D7, "date_end": YESTERDAY,
      "summary_field": "asin", "summary_field_value": ASIN}),
    ("POST", "/basicOpen/tool/competitiveMonitor/list", {"offset": 0, "length": 2}),
    ("POST", "/basicOpen/salesAnalysis/returnOrder/analysisLists",
     {"startDate": D7, "endDate": YESTERDAY, "asinType": "asin", "dateType": 0, "offset": 0, "length": 2}),
    ("POST", "/basicOpen/openapi/service/v3/data/mws/reviews",
     {"date_field": "review_time", "start_date": D7, "end_date": YESTERDAY,
      "sids": "8074", "sort_field": "review_date", "sort_type": "desc", "offset": 0, "length": 2}),
    ("POST", "/erp/sc/data/mws/orders",
     {"sid": 8074, "start_date": D7, "end_date": YESTERDAY, "offset": 0, "length": 2}),
    ("POST", "/erp/sc/routing/fba/fbaStock/fbaList", {"sid": "8074", "offset": 0, "length": 2}),
    ("POST", "/erp/sc/data/fba_report/storageFeeMonth",
     {"sid": 8074, "month": MONTH, "offset": 0, "length": 2}),
    ("POST", "/pb/openapi/newad/spCampaigns", {"sid": 8074, "offset": 0, "length": 2}),
    ("POST", "/pb/openapi/newad/spCampaignReports",
     {"sid": 8074, "report_date": YESTERDAY, "show_detail": 0, "offset": 0, "length": 2}),
    ("POST", "/basicOpen/openapi/storage/fbaWarehouseDetail",
     {"search_field": "asin", "search_value": ASIN, "sid": "8074", "offset": 0, "length": 2}),
    ("POST", "/erp/sc/routing/fbaSug/asin/getDailySalesInfoFeature",
     {"sid": 8074, "asin": ASIN, "sug_type": 3}),
]


def call(path: str, biz: dict, body_mode: bool) -> dict:
    sp = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
          for k, v in biz.items()}
    sp.update({"access_token": token, "app_key": config.app_id, "timestamp": str(int(time.time()))})
    sp["sign"] = sign_request(sp, app_id=config.app_id)
    if body_mode:
        auth_keys = {"access_token", "app_key", "timestamp", "sign"}
        query = {k: v for k, v in sp.items() if k in auth_keys}
        r = httpx.post(f"{BASE}{path}", params=query, json=biz, timeout=30)
    else:
        r = httpx.post(f"{BASE}{path}", params=sp, timeout=30)
    try:
        return r.json()
    except Exception:
        return {"code": -1, "msg": f"http {r.status_code} non-json"}


def brief(d: dict) -> str:
    data = d.get("data")
    if isinstance(data, list):
        shape = f"list[{len(data)}]"
    elif isinstance(data, dict):
        shape = "dict{" + ",".join(list(data.keys())[:4]) + "}"
    else:
        shape = str(data)
    msg = d.get("message") or d.get("msg") or ""
    return f"code={d.get('code')} msg={msg[:20]} data={shape}"


for _, path, biz in ENDPOINTS:
    q = call(path, biz, body_mode=False)
    b = call(path, biz, body_mode=True)
    print(f"{path}\n  query: {brief(q)}\n  body : {brief(b)}")
    time.sleep(0.3)
