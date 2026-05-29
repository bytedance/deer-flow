"""CRM tools for agent integration.

Provides callable tools for CRM-related operations that agents can use
to query external systems for customer, contract, and service object information.
"""

from __future__ import annotations

import logging

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.errors import IntegrationError
from deerflow.integrations.models.crm import Contract, CustomerProfile, ServiceObject
from deerflow.integrations.models.queries import (
    ContractQuery,
    CustomerProfileQuery,
    ServiceObjectQuery,
)
from deerflow.integrations.services.crm_service import CrmService

logger = logging.getLogger(__name__)


class CrmTools:
    """Tool wrappers for CRM operations.

    Each method returns a formatted string suitable for agent consumption,
    including structured data and human-readable summaries.
    """

    def __init__(self, service: CrmService) -> None:
        self._service = service

    async def get_customer_profile(
        self,
        tenant_id: str,
        user_id: str,
        customer_id: str,
    ) -> str:
        """获取客户档案信息。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            customer_id: 客户ID

        Returns:
            格式化的客户档案字符串
        """
        try:
            query = CustomerProfileQuery(
                tenant_id=tenant_id,
                customer_id=customer_id,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.get_customer_profile(query, auth_context)

            profiles: tuple[CustomerProfile, ...] = result.data
            if not profiles:
                return f"未找到客户 (ID: {customer_id})。"

            lines: list[str] = []
            for p in profiles:
                lines.append(f"## 客户档案: {p.display_name}\n")
                lines.append(f"**客户ID**: {p.id}")
                lines.append(f"**行业**: {p.industry or '未指定'}")
                lines.append(f"**区域**: {p.region or '未指定'}")
                lines.append(f"**联系人**: {p.contact_name or '未指定'}")
                lines.append(f"**联系电话**: {p.contact_phone or '未指定'}")
                lines.append(f"**合同数**: {p.contract_count}")
                lines.append(f"**服务对象数**: {p.service_object_count}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get customer profile: %s", e)
            return f"获取客户档案失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting customer profile: %s", e)
            return f"获取客户档案时发生错误: {e}"

    async def search_customers(
        self,
        tenant_id: str,
        user_id: str,
        search_text: str = "",
        industry: str | None = None,
        region: str | None = None,
        limit: int = 20,
    ) -> str:
        """搜索客户列表。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            search_text: 搜索文本（客户名称关键词）
            industry: 行业过滤（可选）
            region: 区域过滤（可选）
            limit: 返回条数限制（默认20）

        Returns:
            格式化的客户列表字符串
        """
        try:
            query = CustomerProfileQuery(
                tenant_id=tenant_id,
                search_text=search_text,
                industry=industry,
                region=region,
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.search_customers(query, auth_context)

            profiles: tuple[CustomerProfile, ...] = result.data
            if not profiles:
                return "未找到匹配的客户记录。"

            lines = [f"找到 {len(profiles)} 个客户：\n"]
            for p in profiles:
                lines.append(
                    f"- **{p.display_name}** (ID: {p.id})\n"
                    f"  行业: {p.industry or '未指定'} | 区域: {p.region or '未指定'}\n"
                    f"  合同数: {p.contract_count} | 服务对象数: {p.service_object_count}"
                )

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to search customers: %s", e)
            return f"搜索客户失败: {e}"
        except Exception as e:
            logger.error("Unexpected error searching customers: %s", e)
            return f"搜索客户时发生错误: {e}"

    async def get_contract_detail(
        self,
        tenant_id: str,
        user_id: str,
        contract_id: str,
    ) -> str:
        """获取合同详情。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            contract_id: 合同ID

        Returns:
            格式化的合同详情字符串
        """
        try:
            query = ContractQuery(
                tenant_id=tenant_id,
                contract_id=contract_id,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.get_contract_detail(query, auth_context)

            contracts: tuple[Contract, ...] = result.data
            if not contracts:
                return f"未找到合同 (ID: {contract_id})。"

            lines: list[str] = []
            for c in contracts:
                status_icon = "✅" if c.status == "active" else "⚠️"
                lines.append(f"## 合同详情: {c.title}\n")
                lines.append(f"**合同ID**: {c.id}")
                lines.append(f"**合同编号**: {c.contract_number}")
                lines.append(f"**客户ID**: {c.customer_id}")
                lines.append(f"**状态**: {status_icon} {c.status}")
                lines.append(f"**服务等级**: {c.service_level or '未指定'}")
                lines.append(f"**开始日期**: {c.start_date}")
                lines.append(f"**结束日期**: {c.end_date or '未指定'}")
                if c.covered_assets:
                    lines.append(f"**覆盖资产**: {', '.join(c.covered_assets)}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get contract detail: %s", e)
            return f"获取合同详情失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting contract detail: %s", e)
            return f"获取合同详情时发生错误: {e}"

    async def list_contracts_by_customer(
        self,
        tenant_id: str,
        user_id: str,
        customer_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        """获取客户的所有合同列表。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            customer_id: 客户ID
            status: 状态过滤（可选）
            limit: 返回条数限制（默认50）

        Returns:
            格式化的合同列表字符串
        """
        try:
            query = ContractQuery(
                tenant_id=tenant_id,
                customer_id=customer_id,
                status=status,
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.list_contracts_by_customer(query, auth_context)

            contracts: tuple[Contract, ...] = result.data
            if not contracts:
                return f"未找到客户 (ID: {customer_id}) 的合同记录。"

            lines = [f"找到 {len(contracts)} 个合同：\n"]
            for c in contracts:
                status_icon = "✅" if c.status == "active" else "⚠️"
                lines.append(
                    f"- {status_icon} **{c.title}** (编号: {c.contract_number})\n"
                    f"  状态: {c.status} | 服务等级: {c.service_level or '未指定'}\n"
                    f"  期间: {c.start_date} ~ {c.end_date or '未指定'}"
                )

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to list contracts: %s", e)
            return f"获取合同列表失败: {e}"
        except Exception as e:
            logger.error("Unexpected error listing contracts: %s", e)
            return f"获取合同列表时发生错误: {e}"

    async def get_service_object_detail(
        self,
        tenant_id: str,
        user_id: str,
        service_object_id: str,
    ) -> str:
        """获取服务对象详情。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            service_object_id: 服务对象ID

        Returns:
            格式化的服务对象详情字符串
        """
        try:
            query = ServiceObjectQuery(
                tenant_id=tenant_id,
                service_object_id=service_object_id,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.get_service_object_detail(query, auth_context)

            objects: tuple[ServiceObject, ...] = result.data
            if not objects:
                return f"未找到服务对象 (ID: {service_object_id})。"

            lines: list[str] = []
            for obj in objects:
                lines.append(f"## 服务对象详情\n")
                lines.append(f"**ID**: {obj.id}")
                lines.append(f"**客户ID**: {obj.customer_id}")
                lines.append(f"**资产ID**: {obj.asset_id or '未关联'}")
                lines.append(f"**对象类型**: {obj.object_type}")
                lines.append(f"**型号**: {obj.model_number or '未指定'}")
                lines.append(f"**序列号**: {obj.serial_number or '未指定'}")
                lines.append(f"**安装日期**: {obj.installation_date or '未指定'}")
                lines.append(f"**保修到期**: {obj.warranty_end_date or '未指定'}")
                lines.append("")

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to get service object detail: %s", e)
            return f"获取服务对象详情失败: {e}"
        except Exception as e:
            logger.error("Unexpected error getting service object detail: %s", e)
            return f"获取服务对象详情时发生错误: {e}"

    async def list_service_objects_by_customer(
        self,
        tenant_id: str,
        user_id: str,
        customer_id: str,
        object_type: str | None = None,
        limit: int = 50,
    ) -> str:
        """获取客户的服务对象列表。

        Args:
            tenant_id: 租户ID
            user_id: 用户ID
            customer_id: 客户ID
            object_type: 对象类型过滤（可选）
            limit: 返回条数限制（默认50）

        Returns:
            格式化的服务对象列表字符串
        """
        try:
            query = ServiceObjectQuery(
                tenant_id=tenant_id,
                customer_id=customer_id,
                object_type=object_type,
                limit=limit,
            )
            auth_context = AuthContext(tenant_id=tenant_id, user_id=user_id)
            result = await self._service.list_service_objects_by_customer(query, auth_context)

            objects: tuple[ServiceObject, ...] = result.data
            if not objects:
                return f"未找到客户 (ID: {customer_id}) 的服务对象记录。"

            lines = [f"找到 {len(objects)} 个服务对象：\n"]
            for obj in objects:
                lines.append(
                    f"- **{obj.object_type}** (ID: {obj.id})\n"
                    f"  型号: {obj.model_number or '未指定'} | 序列号: {obj.serial_number or '未指定'}\n"
                    f"  安装日期: {obj.installation_date or '未指定'} | 保修到期: {obj.warranty_end_date or '未指定'}"
                )

            return "\n".join(lines)

        except IntegrationError as e:
            logger.error("Failed to list service objects: %s", e)
            return f"获取服务对象列表失败: {e}"
        except Exception as e:
            logger.error("Unexpected error listing service objects: %s", e)
            return f"获取服务对象列表时发生错误: {e}"
