"""ERP tools for agent integration.

Provides callable tools for ERP-related operations that agents can use
to query external systems for work orders, spare parts, and inventory.
"""

from __future__ import annotations

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.erp import InventoryItem, SparePart, WorkOrder
from deerflow.integrations.models.queries import (
    InventoryQuery,
    SparePartQuery,
    WorkOrderQuery,
)
from deerflow.integrations.services.erp_service import ErpService

logger = logging.getLogger(__name__)


class ErpTools:
    """Tool wrappers for ERP operations.

    Each method returns a formatted string suitable for agent consumption,
    including structured data and human-readable summaries.
    """

    def __init__(self, service: ErpService) -> None:
        self._service = service

    async def get_work_orders(
        self,
        tenant_id: str,
        user_id: str,
        asset_id: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 20,
    ) -> str:
        """获取工单列表。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            asset_id: 资产ID过滤（可选）
            status: 状态过滤（可选）
            priority: 优先级过滤（可选）
            limit: 返回条数限制（默认20）

        Returns:
            格式化的工单列表字符串
        """
        try:
            query = WorkOrderQuery(
                tenant_id=tenant_id,
                asset_id=asset_id,
                status=status,
                priority=priority,
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.get_work_orders(query, auth_context)

            work_orders: tuple[WorkOrder, ...] = result.data
            if not work_orders:
                return "未找到匹配的工单记录。"

            lines = [f"找到 {len(work_orders)} 个工单：\n"]
            for wo in work_orders:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                    wo.priority, "⚪"
                )
                lines.append(
                    f"- {priority_icon} **{wo.title}** (编号: {wo.order_number})\n"
                    f"  状态: {wo.status} | 优先级: {wo.priority}\n"
                    f"  资产ID: {wo.asset_id or '未关联'} | 负责人: {wo.assigned_to or '未分配'}\n"
                    f"  创建时间: {wo.created_at}"
                )

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get work orders: %s", e)
            return f"获取工单列表失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting work orders: %s", e)
            return f"获取工单列表时发生错误: {e}"

    async def get_work_order_detail(
        self,
        tenant_id: str,
        user_id: str,
        work_order_id: str,
    ) -> str:
        """获取工单详情（含备件使用情况）。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            work_order_id: 工单ID

        Returns:
            格式化的工单详情字符串
        """
        try:
            query = WorkOrderQuery(
                tenant_id=tenant_id,
                work_order_id=work_order_id,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.get_work_order_detail(query, auth_context)

            work_orders: tuple[WorkOrder, ...] = result.data
            if not work_orders:
                return f"未找到工单 (ID: {work_order_id})。"

            lines: list[str] = []
            for wo in work_orders:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                    wo.priority, "⚪"
                )
                lines.append(f"## 工单详情: {wo.title}\n")
                lines.append(f"**工单ID**: {wo.id}")
                lines.append(f"**工单编号**: {wo.order_number}")
                lines.append(f"**状态**: {wo.status}")
                lines.append(f"**优先级**: {priority_icon} {wo.priority}")
                lines.append(f"**描述**: {wo.description or '无'}")
                lines.append(f"**资产ID**: {wo.asset_id or '未关联'}")
                lines.append(f"**负责人**: {wo.assigned_to or '未分配'}")
                lines.append(f"**创建时间**: {wo.created_at}")
                lines.append(f"**计划时间**: {wo.scheduled_at or '未安排'}")
                lines.append(f"**完成时间**: {wo.completed_at or '未完成'}")

                if wo.parts_used:
                    lines.append(f"\n### 备件使用 ({len(wo.parts_used)} 项)")
                    for part in wo.parts_used:
                        cost_str = f" | 单价: {part.unit_cost}" if part.unit_cost else ""
                        lines.append(
                            f"- {part.name} (编号: {part.part_number}) "
                            f"× {part.quantity}{cost_str}"
                        )
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get work order detail: %s", e)
            return f"获取工单详情失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting work order detail: %s", e)
            return f"获取工单详情时发生错误: {e}"

    async def get_parts(
        self,
        tenant_id: str,
        user_id: str,
        category: str | None = None,
        search_text: str = "",
        limit: int = 20,
    ) -> str:
        """搜索备件列表。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            category: 类别过滤（可选）
            search_text: 搜索文本（备件名称或编号关键词）
            limit: 返回条数限制（默认20）

        Returns:
            格式化的备件列表字符串
        """
        try:
            query = SparePartQuery(
                tenant_id=tenant_id,
                category=category,
                search_text=search_text,
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.get_parts(query, auth_context)

            parts: tuple[SparePart, ...] = result.data
            if not parts:
                return "未找到匹配的备件记录。"

            lines = [f"找到 {len(parts)} 个备件：\n"]
            for p in parts:
                stock_icon = "✅" if p.stock_quantity > 0 else "❌"
                low_stock = " ⚠️低库存" if p.min_stock and p.stock_quantity <= p.min_stock else ""
                cost_str = f" | 单价: {p.unit_cost}" if p.unit_cost else ""
                lines.append(
                    f"- {stock_icon} **{p.name}** (编号: {p.part_number})\n"
                    f"  类别: {p.category or '未分类'} | 单位: {p.unit}\n"
                    f"  库存: {p.stock_quantity}{low_stock}{cost_str}"
                )

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get parts: %s", e)
            return f"获取备件列表失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting parts: %s", e)
            return f"获取备件列表时发生错误: {e}"

    async def check_availability(
        self,
        tenant_id: str,
        user_id: str,
        part_id: str,
        warehouse: str | None = None,
    ) -> str:
        """检查备件在各仓库的库存情况。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            part_id: 备件ID
            warehouse: 仓库过滤（可选）

        Returns:
            格式化的库存信息字符串
        """
        try:
            query = InventoryQuery(
                tenant_id=tenant_id,
                part_id=part_id,
                warehouse=warehouse,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.check_availability(query, auth_context)

            items: tuple[InventoryItem, ...] = result.data
            if not items:
                return f"未找到备件 (ID: {part_id}) 的库存记录。"

            total_qty = sum(i.quantity for i in items)
            total_reserved = sum(i.reserved_quantity for i in items)
            available = total_qty - total_reserved

            lines = [
                f"## 备件库存 (Part ID: {part_id})\n",
                f"**总库存**: {total_qty} | **已预留**: {total_reserved} | **可用**: {available}\n",
                f"### 仓库明细 ({len(items)} 个仓库)",
            ]
            for item in items:
                avail = item.quantity - item.reserved_quantity
                lines.append(
                    f"- **{item.warehouse}**: 库存 {item.quantity}, "
                    f"已预留 {item.reserved_quantity}, 可用 {avail}"
                )
                if item.last_restocked_at:
                    lines.append(f"  最近补货: {item.last_restocked_at}")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to check availability: %s", e)
            return f"检查备件库存失败: {e}"
        except Exception as e:
            logger.error("Unexpected error checking availability: %s", e)
            return f"检查备件库存时发生错误: {e}"
