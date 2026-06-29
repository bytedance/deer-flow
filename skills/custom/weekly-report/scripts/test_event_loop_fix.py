#!/usr/bin/env python
"""验证共享 HTTP 客户端在多次 asyncio.run() 调用后仍能正常工作。

这模拟了周报生成时的场景：连续两次 fetch_week_with_provenance() 调用。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 添加 features-tool 到路径
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parents[2] / "features-tool"
if str(_FEATURES_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_FEATURES_TOOL_ROOT))


def test_event_loop_change():
    """测试事件循环变更时客户端是否正确重建。"""
    from ins import client as client_module

    # 保存原始状态
    old_client = client_module._shared_http_client
    old_loop_id = client_module._shared_http_client_loop_id

    try:
        # 重置状态
        client_module._shared_http_client = None
        client_module._shared_http_client_loop_id = None

        first_client = None
        first_loop_id = None
        second_client = None
        second_loop_id = None

        # 第一次事件循环（模拟第一次 fetch_week_with_provenance）
        async def first_loop():
            nonlocal first_client, first_loop_id
            first_client = client_module.get_shared_http_client()
            first_loop_id = client_module._shared_http_client_loop_id
            print(f"循环1: client={id(first_client)}, loop_id={first_loop_id}")

        asyncio.run(first_loop())
        print("循环1 已结束（事件循环已关闭）")

        # 第二次事件循环（模拟第二次 fetch_week_with_provenance）
        async def second_loop():
            nonlocal second_client, second_loop_id
            second_client = client_module.get_shared_http_client()
            second_loop_id = client_module._shared_http_client_loop_id
            print(f"循环2: client={id(second_client)}, loop_id={second_loop_id}")

        asyncio.run(second_loop())
        print("循环2 已结束")

        # 验证
        print()
        if first_client is not second_client:
            print("✅ 成功：客户端在事件循环变更时被正确重建")
            print(f"   第一次客户端 ID: {id(first_client)}")
            print(f"   第二次客户端 ID: {id(second_client)}")
            return True
        else:
            print("❌ 失败：客户端没有被重建，可能导致 'Event loop is closed' 错误")
            return False

    finally:
        # 恢复原始状态
        client_module._shared_http_client = old_client
        client_module._shared_http_client_loop_id = old_loop_id


if __name__ == "__main__":
    print("=" * 60)
    print("测试共享 HTTP 客户端的事件循环处理")
    print("=" * 60)
    print()

    success = test_event_loop_change()

    print()
    print("=" * 60)
    if success:
        print("所有测试通过！")
        sys.exit(0)
    else:
        print("测试失败！")
        sys.exit(1)
