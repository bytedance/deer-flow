"""Quick live test: print FAQ module input/output."""
import json
import os
from deerflow.faq import FaqService, FaqQuery

api_key = os.environ.get("RAGFLOW_API_KEY")
if not api_key:
    raise RuntimeError("RAGFLOW_API_KEY is required for this live test")

service = FaqService(
    base_url="http://host.docker.internal:9380",
    api_key=api_key,
)

query = FaqQuery(
    question="300works 的 Manual、Auto 1、Auto 2、Auto 3 自动化模式有什么区别？现场排查自动化卡点时应该怎么判断问题在哪一段？",
    dataset_ids=["ec218bae4dd611f198d46d41961130d5"],
    top_k=3,
)

import httpx

payload = {"question": query.question, "dataset_ids": query.dataset_ids, "top_k": query.top_k}
with httpx.Client(
    base_url=service._base_url,
    headers=service._build_headers(),
    timeout=service._timeout,
) as client:
    url = f"/api/v1/datasets/{query.dataset_ids[0]}/search"
    resp = client.post(url, json=payload)
    resp.raise_for_status()

with open("/app/logs/faq_raw_response.json", "w", encoding="utf-8") as f:
    json.dump(resp.json(), f, ensure_ascii=False, indent=2)
print("DONE")
