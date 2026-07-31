import logging

from mcp.server.fastmcp import FastMCP

from governance_lingxing_mcp.auth import LingXingAuth
from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.config import LXConfig
from governance_lingxing_mcp.tools.campaign_list import query_campaign_list
from governance_lingxing_mcp.tools.campaign_reports import query_campaign_reports
from governance_lingxing_mcp.tools.competitor import query_competitor_monitor
from governance_lingxing_mcp.tools.fba_inventory import query_fba_inventory
from governance_lingxing_mcp.tools.inventory_days import query_inventory_days
from governance_lingxing_mcp.tools.keyword_monitor import add_keyword_monitor
from governance_lingxing_mcp.tools.keyword_rank import query_keyword_rank
from governance_lingxing_mcp.tools.orders import query_orders
from governance_lingxing_mcp.tools.product_performance import query_product_performance
from governance_lingxing_mcp.tools.profit_report import query_profit_report_asin
from governance_lingxing_mcp.tools.return_analysis import query_return_analysis
from governance_lingxing_mcp.tools.review_rating import query_review_rating
from governance_lingxing_mcp.tools.sales_target import query_sales_target
from governance_lingxing_mcp.tools.sales_trend import query_sales_trend
from governance_lingxing_mcp.tools.search_term_reports import query_search_term_reports
from governance_lingxing_mcp.tools.sp_keyword_reports import query_sp_keyword_reports
from governance_lingxing_mcp.tools.storage_fee import query_storage_fee
from governance_lingxing_mcp.tools.stores import query_marketplaces, query_stores

logger = logging.getLogger(__name__)


def create_server(config: LXConfig | None = None) -> FastMCP:
    if config is None:
        config = LXConfig.from_env()
    auth = LingXingAuth(config)
    client = LingXingClient(config, auth=auth)

    mcp = FastMCP(
        name="lingxing-mcp",
        instructions=(
            "领星 ERP API 包装（18 个工具 + 1 个库存预测工具），覆盖 25 个业务指标。"
            "【闭环规则】几乎所有工具都需要 sid（店铺ID）或 mid（站点ID），"
            "必须先调用 lx_list_stores 获取，再调对应业务工具。"
            "常用链路：ASIN 全维度表现 → lx_product_performance；"
            "广告活动预算+效果 → lx_campaign_list + lx_campaign_reports 按 campaign_id 合并；"
            "关键词排名 → lx_keyword_rank（为空=未监控，经用户确认后 lx_add_keyword_monitor，次日有数据）；"
            "差评 → lx_review_list(star=\"1,2,3\")；销量趋势 → lx_sales_trend；"
            "达成率 → lx_sales_target；配送费 → lx_profit_report_asin；"
            "库存冗余 → lx_fba_inventory；退货率 → lx_return_analysis。"
            "业务数据 T+1，广告数据小时级，评论实时。"
        ),
        host=config.host,
        port=config.port,
    )

    # ========== 基础数据层 ==========

    @mcp.tool()
    def lx_list_stores() -> list[dict]:
        """查询当前账号下所有亚马逊店铺列表。【所有工具的前置依赖，必须最先调用】

        返回 stores[].sid（店铺ID，大部分工具必传）、stores[].mid（站点/国家ID，
        关键词工具必传）、name/seller_id/region/country/status 等。
        """
        return query_stores(client)

    @mcp.tool()
    def lx_list_marketplaces() -> list[dict]:
        """查询所有亚马逊市场列表（mid/name/country/region/currency_code），辅助选择目标市场。"""
        return query_marketplaces(client)

    # ========== 产品数据层 ==========

    @mcp.tool()
    def lx_product_performance(
        sid: list[int] | str | int,
        start_date: str,
        end_date: str,
        summary_field: str = "asin",
        search_field: str | None = None,
        search_value: str | None = None,
        sort_field: str | None = None,
        sort_order: str | None = None,
        currency_code: str | None = None,
        offset: int = 0,
        length: int = 100,
    ) -> dict:
        """查询产品表现（核心工具）：一站式返回销量/流量(sessions_total)/CVR/
        ACOS/ROAS/ACOAS/库存/评分(avg_star+prev_star)/退货率/可售天数(available_days)。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。与官方文档一致的三种形式：
                多店铺传数组（上限200，如 [5609,5608]）；单店铺传字符串 "5608"
                或 int 5608（自动包装为 [5608]）或单元素数组 [5608]。
            start_date: 开始日期 yyyy-MM-dd。
            end_date: 结束日期（与开始日期间隔 ≤ 92天）。
            summary_field: 汇总维度 asin(默认)/parent_asin/msku/sku。
            search_field: 搜索字段 asin/parent_asin/msku/local_sku/item_name。
            search_value: 搜索值（配合 search_field）。
            sort_field: 排序字段（如 volume/amount）。
            sort_order: 排序方向 asc/desc。
            currency_code: 币种 USD(默认)/CNY。
        返回: {"total": 总条数, "list": [全维度产品数据]}。
        """
        return query_product_performance(
            client, sid, start_date, end_date, summary_field, search_field,
            search_value, sort_field, sort_order, currency_code, offset, length,
        )

    @mcp.tool()
    def lx_sales_target(assess_year: str) -> list[dict]:
        """查询店铺销售额目标及达成率（指标#1）。返回 goalAmount1~12(月目标)/
        realAmount1~12(月实际)/completeRateAmount1~12(月完成率)/totalCompleteRate。

        参数:
            assess_year: 目标年份，如 "2026"。
        注意: 仅店铺维度；ASIN级达成率需用户提供目标值后用 lx_product_performance 计算。
        """
        return query_sales_target(client, assess_year)

    @mcp.tool()
    def lx_sales_trend(
        sids: str,
        date_start: str,
        date_end: str,
        summary_field: str,
        summary_field_value: str,
        granularity: str = "day",
    ) -> dict:
        """查询ASIN销量趋势（时间序列）：每日销量/销售额/订单量/BSR。
        回答"近30天销量走势""出单时段分布"类问题。

        参数:
            sids: 店铺ID，逗号分隔，从 lx_list_stores 获取。
            date_start: 开始日期 yyyy-MM-dd。
            date_end: 结束日期。
            summary_field: 汇总维度 asin/parent_asin/msku/sku/spu。
            summary_field_value: 维度值（如具体ASIN）。
            granularity: day(默认，聚合为天)/hour(原始小时段)。
        返回: {"data": [{r_date, volume, order_items, amount, price, sales_rank}], "total": {}}。
        """
        return query_sales_trend(
            client, sids, date_start, date_end, summary_field, summary_field_value, granularity
        )

    # ========== 广告数据层 ==========

    @mcp.tool()
    def lx_campaign_reports(
        sid: int,
        start_date: str,
        end_date: str,
        campaign_id: int | None = None,
        show_detail: int = 0,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询SP广告活动报表（指标#7 CVR/#8 ACOS/#9 ROAS）。入参为日期范围，
        服务端内部按天循环聚合（≤31天），acos/roas/cvr/ctr/cpc 由求和结果重算。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。
            start_date: 开始日期 yyyy-MM-dd（单次跨度 ≤ 31天）。
            end_date: 结束日期。
            campaign_id: 可选活动ID过滤（聚焦单个活动）。
            show_detail: 是否返回1d/7d/14d/30d归因字段，0/1。
        返回: [{campaign_id, campaign_name, impressions, clicks, cost, orders,
               sales, acos, roas, cvr, ctr, cpc}...]。
        注意: 不返回预算，预算用 lx_campaign_list 获取后按 campaign_id 合并。
        """
        return query_campaign_reports(
            client, sid, start_date, end_date, campaign_id, show_detail, offset, length
        )

    @mcp.tool()
    def lx_campaign_list(
        sid: int,
        state: str | None = None,
        offset: int = 0,
        length: int = 15,
        next_token: str | None = None,
    ) -> list[dict]:
        """查询SP广告活动列表（指标#10 预算）。返回 campaign_id/name/state/
        daily_budget(每日预算)/targeting_type/start_date/end_date。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。
            state: 状态过滤 enabled/paused/archived。
        闭环: 与 lx_campaign_reports 通过 campaign_id 关联合并"预算+效果"视图。
        """
        return query_campaign_list(client, sid, state, offset, length, next_token)

    @mcp.tool()
    def lx_sp_keyword_reports(
        sid: int,
        start_date: str,
        end_date: str,
        show_detail: int = 0,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询SP广告关键词报表。入参为日期范围，服务端内部按天循环聚合（≤31天）。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。
            start_date: 开始日期 yyyy-MM-dd（单次跨度 ≤ 31天）。
            end_date: 结束日期。
        返回: [{keyword_id, keyword_text, match_type, campaign_id, campaign_name,
               ad_group_id, impressions, clicks, cost, orders, sales, acos, roas...}...]。
        """
        return query_sp_keyword_reports(client, sid, start_date, end_date, show_detail, offset, length)

    @mcp.tool()
    def lx_search_term_reports(
        sid: int,
        target_type: str,
        start_date: str,
        end_date: str,
        show_detail: int = 0,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询SP广告搜索词报表（指标#13 关键词-流量占比）。入参为日期范围，
        服务端内部按天循环聚合（≤31天）。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。
            target_type: keyword(关键词)/target(商品投放)，必填。
            start_date: 开始日期 yyyy-MM-dd（单次跨度 ≤ 31天）。
            end_date: 结束日期。
        返回: [{query(用户搜索词), keyword_text, match_type, campaign_id, asin,
               impressions, clicks, cost, orders, sales}...]。
            流量占比 = 某词 clicks / 全部搜索词总 clicks。
        """
        return query_search_term_reports(
            client, sid, target_type, start_date, end_date, show_detail, offset, length
        )

    # ========== 订单/财务层 ==========

    @mcp.tool()
    def lx_orders(
        sid: int,
        start_date: str,
        end_date: str,
        date_type: int | None = None,
        order_status: str | None = None,
        fulfillment_channel: int | None = None,
        offset: int = 0,
        length: int = 100,
    ) -> dict:
        """查询亚马逊订单列表。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。
            start_date: 开始日期 yyyy-MM-dd（跨度 ≤ 1年）。
            end_date: 结束日期。
            date_type: 1=订购时间(站点)/2=修改时间(北京)/3=平台更新(UTC)/10=发货时间。
            order_status: Pending/Unshipped/PartiallyShipped/Shipped/Canceled。
            fulfillment_channel: 1=FBA/2=FBM。
        返回: {"total": n, "data": [{amazon_order_id, order_status,
               order_total_amount, item_list[{asin, seller_sku, quantity_ordered}]...}]}。
        注意: 无ASIN筛选参数，按ASIN分析请拉取后按 item_list[].asin 过滤。
        """
        return query_orders(
            client, sid, start_date, end_date, date_type, order_status,
            fulfillment_channel, offset, length,
        )

    @mcp.tool()
    def lx_profit_report_asin(
        sids: list[int] | str | int,
        start_date: str,
        end_date: str,
        search_field: str | None = None,
        search_value: list[str] | None = None,
        mids: list[int] | None = None,
        monthly_query: bool | None = None,
        currency_code: str | None = None,
        order_status: str | None = None,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询ASIN维度利润报表（指标#22 配送费 fbaDeliveryFee）。返回销量/销售额/
        广告费/FBA配送费/仓储费/佣金/退款/赔偿/毛利润/毛利率明细。

        参数:
            sids: 店铺ID列表，从 lx_list_stores 获取（int/字符串自动规范化为单元素数组）。
            start_date: 开始日期 yyyy-MM-dd（跨度 ≤ 31天）。
            end_date: 结束日期。
            search_field: 搜索字段 "asin"。
            search_value: ASIN列表。
            monthly_query: 是否按月汇总（默认按天）。
            currency_code: CNY/USD。
            order_status: Disbursed/Deferred/All。
        """
        return query_profit_report_asin(
            client, sids, start_date, end_date, search_field, search_value,
            mids, monthly_query, currency_code, order_status, offset, length,
        )

    # ========== 库存数据层 ==========

    @mcp.tool()
    def lx_fba_inventory(
        sid: str,
        search_field: str | None = None,
        search_value: str | None = None,
        redundant_threshold_days: int = 90,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询FBA库存列表含库龄分布（指标#23 冗余成本/#24 冗余数量）。
        每行附加 redundant_quantity（超阈值库龄段库存和）与 redundant_cost（×单位成本）。

        参数:
            sid: 店铺ID（逗号分隔支持多个），从 lx_list_stores 获取。
            search_field: asin/msku/fnsku/sku。
            search_value: 搜索值。
            redundant_threshold_days: 冗余阈值天数，默认90（可选180/271/365）。
        返回: [{asin, msku, afn_fulfillable_quantity, inv_age_*_days(各库龄段),
               cost, redundant_quantity, redundant_cost}...]。
        """
        return query_fba_inventory(
            client, sid, search_field, search_value, redundant_threshold_days, offset, length
        )

    @mcp.tool()
    def lx_storage_fee(
        sid: int,
        fee_type: str,
        month: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        offset: int = 0,
        length: int = 1000,
    ) -> list[dict]:
        """查询FBA仓储费（月仓储费+长期仓储费），辅助库存冗余成本分析。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。
            fee_type: monthly(月仓储费，必填 month=yyyy-MM) /
                      long_term(长期仓储费，必填 start_date/end_date)。
        注意: 无ASIN筛选参数，请拉取后按 asin 过滤。
        """
        return query_storage_fee(client, sid, fee_type, month, start_date, end_date, offset, length)

    # ========== 关键词层 ==========

    @mcp.tool()
    def lx_keyword_rank(
        offset: int = 0,
        length: int = 20,
        mid: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        search_field: str | None = None,
        search_value: str | None = None,
    ) -> list[dict]:
        """查询关键词排名（指标#11 广告位 is_sponsored=1 / #12 自然位 is_sponsored=0）。

        参数:
            mid: 国家/市场ID（从 lx_list_stores 获取；不传查全部站点）。
            start_date: 开始日期 yyyy-MM-dd。
            end_date: 结束日期。
            search_field: key_word/asin。
            search_value: 搜索值（如 "yoga mat"）。
        返回: [{key_word, asin, rank, page, is_sponsored, type, monitor_time}...]。
        闭环: 仅返回已监控关键词；返回提示未监控时，经用户确认后调
              lx_add_keyword_monitor 添加（次日有数据）。
        """
        return query_keyword_rank(
            client, offset, length, mid, start_date, end_date, search_field, search_value
        )

    @mcp.tool()
    def lx_add_keyword_monitor(
        mid: int,
        keywords: list[str],
        asins: list[str],
        types: list[int],
        is_sponsors: list[int],
        postcodes: list[str] | None = None,
    ) -> dict:
        """添加关键词排名监控（写操作/Beta）。关键词未监控时的闭环工具。

        参数:
            mid: 国家/市场ID，从 lx_list_stores 获取。
            keywords: 关键词列表。
            asins: 监控的ASIN列表。
            types: 监控范围 1=PC端, 2=移动端。
            is_sponsors: 是否监控广告位 0=否, 1=是。
            postcodes: 邮编（不传用默认）。
        注意: 调用前先用 lx_keyword_rank 查重并向用户确认；新监控次日才有数据；
              失败时提示用户到领星ERP网页端手动添加。
        """
        return add_keyword_monitor(client, mid, keywords, asins, types, is_sponsors, postcodes)

    # ========== 竞品监控层 ==========

    @mcp.tool()
    def lx_competitor_monitor(
        search_field: str | None = None,
        search_value: str | None = None,
        levels: list[int] | None = None,
        update_time_start: str | None = None,
        update_time_end: str | None = None,
        offset: int = 0,
        length: int = 20,
    ) -> list[dict]:
        """查询竞品监控数据（指标#16 竞品-排名 / #17 竞品-价格）。

        参数:
            search_field: asin。
            search_value: ASIN（多个逗号分隔，上限200）。
            levels: 竞品等级 1=A,2=B,3=C,4=D。
        返回: [{asin, title, big_category_rank(BSR), small_ranks, price,
               buybox_price, avg_price, star, review_num}...]。
        注意: 竞品需在领星ERP网页端（工具→竞品监控）预先添加；查询为空会返回提示。
        """
        return query_competitor_monitor(
            client, search_field, search_value, levels, update_time_start, update_time_end, offset, length
        )

    # ========== 退货分析层 ==========

    @mcp.tool()
    def lx_return_analysis(
        start_date: str,
        end_date: str,
        asin_type: str,
        date_type: int,
        store_id: list[int] | None = None,
        mids: list[int] | None = None,
        search_field: str | None = None,
        search_value: list[str] | None = None,
        sort_field: str | None = None,
        offset: int = 0,
        length: int = 100,
    ) -> list[dict]:
        """查询退货分析（指标#21 退货率，含环比对比与FBA/FBM分布）。

        参数:
            start_date: 开始日期 yyyy-MM-dd（跨度 ≤ 366天）。
            end_date: 结束日期。
            asin_type: 维度 asin/msku/parentAsin/sku/spu。
            date_type: 0=退货时间, 1=下单时间。
            store_id: 店铺ID列表，从 lx_list_stores 获取。
            search_field: msku/asin/parentAsin/localSku/localName/spu。
            search_value: 搜索值列表。
        返回: [{asin, curReturnGoodsCount, curReturnGoodsVolumeRatio(当期退货率),
               preReturnGoodsVolumeRatio(上期), returnGoodsVolumeRatioDiff(环比)}...]。
        """
        return query_return_analysis(
            client, start_date, end_date, asin_type, date_type, store_id,
            mids, search_field, search_value, sort_field, offset, length,
        )

    # ========== 评论/评分层 ==========

    @mcp.tool()
    def lx_review_list(
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
        """查询Review明细列表（指标#20 新增差评，辅助#19 评分变化）。实时数据。

        参数:
            date_field: review_time(评价时间)/create_time/last_update_time。
            start_date: 开始日期 yyyy-MM-dd。
            end_date: 结束日期。
            sids: 店铺ID，逗号分隔，从 lx_list_stores 获取。
            star: 星级筛选，如 "1,2,3" 拉取差评。
            search_field: asin/parent_asin/amazon_order_id/author/review_id 等。
            search_value: 搜索值。
        返回: [{asin, last_star, last_title, last_content, review_date, author,
               images, videos, amazon_order_list(关联订单)}...]。
        闭环: 查"昨天新增差评" → lx_list_stores 得 sids → 本工具(star="1,2,3")。
        """
        return query_review_rating(
            client, date_field, start_date, end_date, sids, sort_field, sort_type,
            search_field, search_value, status, star, offset, length,
        )

    # ========== 附加工具（销量预测口径的可售天数） ==========

    @mcp.tool()
    def lx_inventory_days(
        sid: int,
        asin: str,
        sug_type: int = 3,
        mode: int | None = None,
    ) -> dict:
        """查询 FBA 库存 + 销量预测并合并，返回可售天数（预测口径，
        与 lx_product_performance 的 available_days 统计口径互补）。

        参数:
            sid: 店铺ID，从 lx_list_stores 获取。
            asin: 商品 ASIN。
            sug_type: 1 建议采购量 / 2 建议本地仓发货量 / 3 建议海外仓发货量（默认）。
            mode: 可选预测模式。
        返回: {asin, in_stock, in_transit, daily_sales, available_days}。
        """
        return query_inventory_days(client, sid, asin, sug_type, mode)

    return mcp


def main():
    logging.basicConfig(level=logging.INFO)
    mcp = create_server()
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
