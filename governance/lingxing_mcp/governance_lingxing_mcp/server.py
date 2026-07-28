import logging

from mcp.server.fastmcp import FastMCP

from governance_lingxing_mcp.auth import LingXingAuth
from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.config import LXConfig
from governance_lingxing_mcp.tools.campaign_perf import query_campaign_perf
from governance_lingxing_mcp.tools.inventory_days import query_inventory_days
from governance_lingxing_mcp.tools.keyword_rank import query_keyword_rank
from governance_lingxing_mcp.tools.keyword_share import query_keyword_share
from governance_lingxing_mcp.tools.parent_ad import query_parent_ad
from governance_lingxing_mcp.tools.parent_sales import query_parent_sales
from governance_lingxing_mcp.tools.review_rating import query_review_rating

logger = logging.getLogger(__name__)


def create_server(config: LXConfig | None = None) -> FastMCP:
    if config is None:
        config = LXConfig.from_env()
    auth = LingXingAuth(config)
    client = LingXingClient(config, auth=auth)

    mcp = FastMCP(
        name="lingxing-mcp",
        instructions=(
            "领星 ERP API 包装：产品表现 / SP 广告 / 关键词 / 评论 / 库存。"
            " 提供 7 个工具：lx_parent_sales, lx_campaign_perf, lx_parent_ad, "
            "lx_keyword_share, lx_keyword_rank, lx_review_rating, lx_inventory_days。"
            " 业务数据 T+1，广告数据小时级，评论实时。"
        ),
        host=config.host,
        port=config.port,
    )

    @mcp.tool()
    def lx_parent_sales(
        sid: list | str,
        start_date: str,
        end_date: str,
        search_value: list | None = None,
        summary_field: str = "parent_asin",
        length: int = 100,
    ) -> list[dict]:
        """查询产品表现（父ASIN 级）：达成率/Sessions/CVR/Orders/销售额。T+1 数据。

        参数:
            sid: 店铺 id 列表（也可传单个值）。
            start_date: 起始日期，格式 YYYY-MM-DD。
            end_date: 结束日期，格式 YYYY-MM-DD。
            search_value: 可选 parent_asin 过滤列表。
            summary_field: 汇总维度，默认 parent_asin。
            length: 单页条数，默认 100。
        """
        return query_parent_sales(client, sid, start_date, end_date, search_value, summary_field, length)

    @mcp.tool()
    def lx_campaign_perf(
        sid: int,
        report_date: str,
        profile_id: int | None = None,
        show_detail: int = 0,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询 SP 广告活动报表：targeting_type/clicks/cost/sales/orders/units 等。小时级数据。

        参数:
            sid: 店铺 id。与 profile_id 二选一。
            report_date: 报告日期，格式 YYYY-MM-DD。
            profile_id: 可选广告 profile id。提供时覆盖 sid。
            show_detail: 是否返回明细，0/1。
            offset: 分页起始偏移。
            length: 单页条数，默认 100。
        """
        return query_campaign_perf(client, sid, report_date, profile_id, show_detail, offset, length)

    @mcp.tool()
    def lx_parent_ad(
        sid: int,
        report_date: str,
        profile_id: int | None = None,
        show_detail: int = 0,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询 SP 广告商品报表：impressions/clicks/cost/sales/orders/units 等。小时级数据。

        参数:
            sid: 店铺 id。与 profile_id 二选一。
            report_date: 报告日期，格式 YYYY-MM-DD。
            profile_id: 可选广告 profile id。提供时覆盖 sid。
            show_detail: 是否返回明细，0/1。
            offset: 分页起始偏移。
            length: 单页条数，默认 100。
        """
        return query_parent_ad(client, sid, report_date, profile_id, show_detail, offset, length)

    @mcp.tool()
    def lx_keyword_share(
        sid: int,
        report_date: str,
        profile_id: int | None = None,
        target_type: str = "keyword",
        show_detail: int = 0,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询 SP 用户搜索词报表：query/target_id/match_type/clicks/cost/sales 等。T+1 数据。

        参数:
            sid: 店铺 id。与 profile_id 二选一。
            report_date: 报告日期，格式 YYYY-MM-DD。
            profile_id: 可选广告 profile id。提供时覆盖 sid。
            target_type: keyword 关键词 / target 商品投放。
            show_detail: 是否返回明细，0/1。
            offset: 分页起始偏移。
            length: 单页条数，默认 100。
        """
        return query_keyword_share(client, sid, report_date, profile_id, target_type, show_detail, offset, length)

    @mcp.tool()
    def lx_keyword_rank(
        offset: int = 0,
        length: int = 20,
        mid: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """查询关键词排名监控列表：key_word/rank/current_page_rank/sbv_page/asin 等。T+1 数据。

        参数:
            offset: 分页起始偏移。
            length: 单页条数，默认 20。
            mid: 可选监控 id 过滤。
            start_date: 可选起始日期，格式 YYYY-MM-DD。
            end_date: 可选结束日期，格式 YYYY-MM-DD。
        """
        return query_keyword_rank(client, offset, length, mid, start_date, end_date)

    @mcp.tool()
    def lx_review_rating(
        date_field: str,
        start_date: str,
        end_date: str,
        sids: str | None = None,
        sort_field: str = "review_date",
        sort_type: str = "desc",
        search_field: str | None = None,
        search_value: str | None = None,
        status: str | None = None,
        star: str | None = None,
        offset: int = 0,
        length: int = 20,
    ) -> list[dict]:
        """查询评论管理 Review：review_id/asin/last_star/last_title/last_content/author 等。实时数据。

        参数:
            date_field: review_time / create_time / last_update_time。
            start_date: 起始日期，格式 YYYY-MM-DD。
            end_date: 结束日期，格式 YYYY-MM-DD。
            sids: 可选店铺 id 字符串过滤。
            sort_field: 排序字段，默认 review_date。
            sort_type: 排序方向，默认 desc。
            search_field: 可选搜索字段。
            search_value: 可选搜索值。
            status: 可选评论状态过滤。
            star: 可选星级过滤。
            offset: 分页起始偏移。
            length: 单页条数，默认 20。
        """
        return query_review_rating(
            client,
            date_field,
            start_date,
            end_date,
            sids,
            sort_field,
            sort_type,
            search_field,
            search_value,
            status,
            star,
            offset,
            length,
        )

    @mcp.tool()
    def lx_inventory_days(
        sid: int,
        asin: str,
        sug_type: int = 3,
        mode: int | None = None,
    ) -> dict:
        """查询 FBA 库存 + 销量预测并合并，返回可售天数。

        参数:
            sid: 店铺 id。
            asin: 商品 ASIN。
            sug_type: 1 建议采购量 / 2 建议本地仓发货量 / 3 建议海外仓发货量（默认）。
            mode: 可选预测模式。
        返回:
            {asin, in_stock, in_transit, daily_sales, available_days}
        """
        return query_inventory_days(client, sid, asin, sug_type, mode)

    return mcp


def main():
    logging.basicConfig(level=logging.INFO)
    mcp = create_server()
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
