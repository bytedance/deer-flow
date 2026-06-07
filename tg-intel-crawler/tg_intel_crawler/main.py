import asyncio
import logging
from pathlib import Path

import click
import yaml

from tg_intel_crawler.collector.candidate_pool import CandidatePool
from tg_intel_crawler.collector.client import TGClient
from tg_intel_crawler.collector.bot_query_generator import QueryGenerator
from tg_intel_crawler.collector.bot_response_parser import BotResponseParser
from tg_intel_crawler.collector.bot_search import BotSearchClient, BotUnavailable
from tg_intel_crawler.collector.bot_search_throttle import (
    BotQueryLimitExceeded,
    BotQueryThrottle,
)
from tg_intel_crawler.collector.detail_fetcher import DetailFetcher
from tg_intel_crawler.collector.group_extractor import GroupExtractor
from tg_intel_crawler.collector.group_finder import GroupFinder
from tg_intel_crawler.collector.join_throttle import (
    DailyLimitExceeded,
    JoinThrottle,
)
from tg_intel_crawler.collector.joined_scanner import JoinedGroupsScanner
from tg_intel_crawler.collector.message_fetcher import MessageFetcher, MessageData
from tg_intel_crawler.collector.twitter_client import (
    TikHubAuthError,
    TwitterClient,
)
from tg_intel_crawler.collector.twitter_fetcher import TweetData, TwitterFetcher
from tg_intel_crawler.filter.keyword_filter import KeywordFilter
from tg_intel_crawler.filter.llm_filter import LLMFilter
from tg_intel_crawler.probe.reporter import ProbeReporter
from tg_intel_crawler.probe.runner import ProbeRunner
from tg_intel_crawler.probe.sampler import Sampler
from tg_intel_crawler.storage.exporter import Exporter, IntelRecord
from tg_intel_crawler.utils.logger import setup_logger
from tg_intel_crawler.utils.rate_limiter import RateLimiter

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
KEYWORDS_PATH = Path(__file__).parent.parent / "config" / "keywords.yaml"
DEFAULT_CANDIDATES_PATH = Path(__file__).parent.parent / "config" / "discovered_groups.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _candidates_path(config: dict) -> str:
    """Resolve candidate pool path from config (with default)."""
    return (
        config.get("discovery", {}).get("candidates_path")
        or str(DEFAULT_CANDIDATES_PATH)
    )


def _candidate_link(entry: dict) -> str:
    """Build the full https://t.me/... link for a candidate dict.

    Private groups (with an invite_hash) → https://t.me/+<hash>,
    public groups → https://t.me/<key>.
    """
    if entry.get("invite_hash"):
        return f"https://t.me/+{entry['invite_hash']}"
    return f"https://t.me/{entry.get('key', '')}"


def _make_join_throttle(config: dict) -> JoinThrottle:
    join_cfg = config.get("join", {}) or {}
    return JoinThrottle(
        min_interval=join_cfg.get("min_interval", 30),
        max_interval=join_cfg.get("max_interval", 90),
        daily_limit=join_cfg.get("daily_limit", 20),
    )


@click.group()
def cli():
    """Telegram 黑灰产情报爬虫工具 - 字节跳动相关"""
    setup_logger()


@cli.command()
def init():
    """Initialize configuration (interactive setup)."""
    config = load_config()
    click.echo("=== Telegram 黑灰产情报爬虫 - 初始化配置 ===\n")

    api_id = click.prompt("Telegram API ID", type=int)
    api_hash = click.prompt("Telegram API Hash")
    phone = click.prompt("Phone number (with country code, e.g. +86xxx)")

    config["telegram"]["api_id"] = api_id
    config["telegram"]["api_hash"] = api_hash
    config["telegram"]["phone"] = phone

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    click.echo(f"\n✅ Config saved to {CONFIG_PATH}")
    click.echo("Run 'crawl' command to start crawling.")


@cli.command()
@click.option("--mode", type=click.Choice(["history", "realtime", "both"]), default="both")
@click.option("--days", default=7, help="Days of history to crawl")
@click.option(
    "--include-joined/--no-include-joined",
    default=None,
    help="Also crawl every group/channel this account is currently in "
    "(via iter_dialogs). Defaults to discovery.include_joined in config.",
)
@click.option(
    "--joined-only",
    is_flag=True,
    default=False,
    help="Crawl ONLY joined groups, ignoring config.groups.",
)
@click.option(
    "--exclude",
    default="",
    help="Comma-separated usernames or chat_ids to skip (overrides discovery.exclude_joined).",
)
def crawl(mode: str, days: int, include_joined, joined_only: bool, exclude: str):
    """Start crawling Telegram groups."""
    asyncio.run(_crawl_async(mode, days, include_joined, joined_only, exclude))


async def _crawl_async(
    mode: str,
    days: int,
    include_joined_flag,
    joined_only: bool,
    exclude_arg: str,
):
    """Main async crawl logic."""
    logger = logging.getLogger("tg_crawler")
    config = load_config()

    # Initialize components
    rate_limiter = RateLimiter(
        delay_min=config["crawl"]["delay_min"],
        delay_max=config["crawl"]["delay_max"],
    )
    keyword_filter = KeywordFilter(str(KEYWORDS_PATH))
    llm_filter = LLMFilter(config["llm"])
    exporter = Exporter(
        output_dir=config["output"]["dir"],
        formats=config["output"]["format"],
    )
    extractor = GroupExtractor()
    candidate_pool = CandidatePool(_candidates_path(config))

    # Resolve include_joined: CLI flag wins, fall back to config.
    discovery_cfg = config.get("discovery", {}) or {}
    if joined_only:
        effective_include_joined = True
    elif include_joined_flag is not None:
        effective_include_joined = include_joined_flag
    else:
        effective_include_joined = bool(discovery_cfg.get("include_joined", False))

    # Resolve exclude list.
    excluded_usernames: set[str] = set()
    excluded_chat_ids: set[int] = set()
    raw_exclude = (
        [x.strip() for x in exclude_arg.split(",") if x.strip()]
        if exclude_arg
        else list(discovery_cfg.get("exclude_joined") or [])
    )
    for token in raw_exclude:
        token = token.lstrip("@")
        if token.lstrip("-").isdigit():
            excluded_chat_ids.add(int(token))
        else:
            excluded_usernames.add(token)

    async with TGClient(str(CONFIG_PATH)) as tg:
        client = tg.client
        fetcher = MessageFetcher(client, rate_limiter)

        # Resolve effective group list.
        configured = list(config.get("groups", []) or [])
        joined_groups: list[str] = []
        if effective_include_joined:
            scanner = JoinedGroupsScanner(client)
            joined = await scanner.list_joined(
                include_channels=bool(
                    discovery_cfg.get("scan_includes_channels", True)
                ),
                exclude_usernames=excluded_usernames,
                exclude_chat_ids=excluded_chat_ids,
            )
            joined_groups = [g.link for g in joined]
            logger.info(
                f"📡 iter_dialogs: {len(joined_groups)} joined groups/channels"
            )

        if joined_only:
            sources = joined_groups
        else:
            # Dedupe while preserving order — config.groups first, joined after.
            seen: set[str] = set()
            sources = []
            for link in configured + joined_groups:
                if link not in seen:
                    seen.add(link)
                    sources.append(link)

        groups = sources
        if not groups:
            logger.warning(
                "No groups to crawl. Configure groups or pass --include-joined."
            )
            return

        # History mode
        if mode in ("history", "both"):
            for group in groups:
                await _crawl_one_group(
                    group,
                    days=days,
                    fetcher=fetcher,
                    keyword_filter=keyword_filter,
                    llm_filter=llm_filter,
                    exporter=exporter,
                    extractor=extractor,
                    candidate_pool=candidate_pool,
                    config=config,
                    logger=logger,
                )

        # Realtime mode
        if mode in ("realtime", "both"):
            logger.info("👂 Switching to realtime monitoring...")

            async def on_new_message(msg_data: MessageData):
                # Always archive every realtime message to raw FIRST so the
                # raw store keeps accumulating even if the message gets
                # dropped later by keyword/LLM filters.
                exporter.export_raw(
                    [msg_data.to_dict()], group_name=msg_data.group_name
                )

                # Reverse-discovery on every realtime message too.
                signals = extractor.extract_from([msg_data])
                if signals:
                    candidate_pool.merge(signals)
                    candidate_pool.flush()

                if keyword_filter.matches(msg_data.text):
                    logger.info(f"🔔 Hit: [{msg_data.group_name}] {msg_data.text[:60]}...")
                    results = await llm_filter.analyze_batch([msg_data.text])
                    if results and results[0].is_relevant:
                        record = IntelRecord(
                            id=f"msg_{msg_data.msg_id}",
                            source_group=msg_data.group_name,
                            date=msg_data.date,
                            sender_id=msg_data.sender_id,
                            sender_name=msg_data.sender_name,
                            sender_username=msg_data.sender_username,
                            original_text=msg_data.text,
                            risk_type=results[0].risk_type,
                            risk_level=results[0].risk_level,
                            entities=results[0].entities,
                            summary=results[0].summary,
                            llm_model=config["llm"]["model"],
                        )
                        exporter.export_filtered([record])
                        logger.info(f"💾 Saved: [{record.risk_level}] {record.summary}")

            fetcher.start_realtime(groups, on_new_message)
            await client.run_until_disconnected()


async def _crawl_one_group(
    group: str,
    *,
    days: int,
    fetcher: MessageFetcher,
    keyword_filter: KeywordFilter,
    llm_filter: LLMFilter,
    exporter: Exporter,
    extractor: GroupExtractor,
    candidate_pool: CandidatePool,
    config: dict,
    logger: logging.Logger,
) -> dict:
    """Fetch history for a single group and run it through the full
    raw → reverse-discovery → keyword → LLM → export pipeline.

    Returns a dict with per-group counters: {fetched, raw_added, kept,
    relevant, high, medium, low}.
    """
    stats = {
        "fetched": 0, "raw_added": 0, "kept": 0,
        "relevant": 0, "high": 0, "medium": 0, "low": 0,
    }
    messages = await fetcher.fetch_history(group, days=days)
    stats["fetched"] = len(messages)
    if not messages:
        return stats

    raw_dicts = [m.to_dict() for m in messages]
    group_name = messages[0].group_name if messages else "unknown"
    stats["raw_added"] = exporter.export_raw(raw_dicts, group_name=group_name)
    logger.info(f"📥 Raw archive: +{stats['raw_added']} new (of {len(raw_dicts)} fetched)")

    # Reverse-discovery before LLM so the pool grows even if LLM fails.
    signals = extractor.extract_from(messages)
    if signals:
        candidate_pool.merge(signals)
        candidate_pool.flush()
        logger.info(
            f"🧭 Discovered {len(signals)} group signals "
            f"(pool size now: {len(candidate_pool.list_all())})"
        )

    filtered_texts: list[str] = []
    filtered_messages: list[MessageData] = []
    for msg in messages:
        if keyword_filter.matches(msg.text):
            filtered_texts.append(msg.text)
            filtered_messages.append(msg)
    stats["kept"] = len(filtered_texts)
    logger.info(f"Keyword filter: {len(filtered_texts)}/{len(messages)} messages passed")
    if not filtered_texts:
        return stats

    logger.info(f"🤖 LLM analyzing {len(filtered_texts)} messages...")
    results = await llm_filter.analyze(filtered_texts)
    if len(results) != len(filtered_texts):
        logger.warning(
            f"⚠️ LLM returned {len(results)} results for "
            f"{len(filtered_texts)} inputs — dumping to errors/"
        )
        exporter.export_failed_batch(
            [m.to_dict() for m in filtered_messages],
            reason=(
                f"llm_result_count_mismatch: "
                f"got={len(results)} expected={len(filtered_texts)}"
            ),
            group_name=group_name,
        )
        if not results:
            return stats

    records: list[IntelRecord] = []
    for msg, result in zip(filtered_messages, results):
        if result.is_relevant:
            records.append(IntelRecord(
                id=f"msg_{msg.msg_id}",
                source_group=msg.group_name,
                date=msg.date,
                sender_id=msg.sender_id,
                sender_name=msg.sender_name,
                sender_username=msg.sender_username,
                original_text=msg.text,
                risk_type=result.risk_type,
                risk_level=result.risk_level,
                entities=result.entities,
                summary=result.summary,
                llm_model=config["llm"]["model"],
            ))

    exporter.export_filtered(records)
    stats["relevant"] = len(records)
    stats["high"] = sum(1 for r in records if r.risk_level == "high")
    stats["medium"] = sum(1 for r in records if r.risk_level == "medium")
    stats["low"] = sum(1 for r in records if r.risk_level == "low")
    logger.info(
        f"📊 Results: high={stats['high']}, medium={stats['medium']}, low={stats['low']}"
    )
    return stats


@cli.command()
@click.option("--keywords", required=True, help="Comma-separated search keywords")
@click.option("--auto-join/--no-auto-join", default=False, help="Auto join found groups")
@click.option("--list-only", is_flag=True, default=False,
              help="Only search and print results; never prompt or join "
                   "(non-interactive — safe for automation/agents).")
def discover(keywords: str, auto_join: bool, list_only: bool):
    """Discover relevant Telegram groups by keywords."""
    asyncio.run(_discover_async(keywords.split(","), auto_join, list_only))


async def _discover_async(keywords: list[str], auto_join: bool, list_only: bool = False):
    logger = logging.getLogger("tg_crawler")
    config = load_config()
    throttle = _make_join_throttle(config)

    async with TGClient(str(CONFIG_PATH)) as tg:
        finder = GroupFinder(tg.client)

        # Warm up the already-joined cache so we don't waste join quota.
        scanner = JoinedGroupsScanner(tg.client)
        joined = await scanner.list_joined()
        throttle.warmup(
            usernames={g.username for g in joined if g.username},
            chat_ids={g.chat_id for g in joined},
        )

        groups = await finder.search_groups(keywords)

        if not groups:
            logger.info("No groups found.")
            return

        click.echo(f"\nFound {len(groups)} groups:\n")
        for i, g in enumerate(groups):
            click.echo(f"  [{i+1}] {g['title']} (@{g['username']}) - {g['members_count']} members")

        if list_only:
            # Non-interactive: just report, never prompt or join.
            return

        if auto_join:
            for g in groups:
                if not g["username"]:
                    continue
                try:
                    await throttle.run_join(
                        g["username"], lambda u=g["username"]: finder.join_group(u)
                    )
                except DailyLimitExceeded:
                    click.echo("⏸️  Daily join limit hit; stopping.")
                    break
        else:
            selection = click.prompt(
                "\nEnter numbers to add (comma-separated), or 'all', or 'none'",
                default="none",
            )
            if selection == "all":
                selected = groups
            elif selection == "none" or selection == "":
                selected = []
            else:
                try:
                    indices = [int(x.strip()) - 1 for x in selection.split(",")]
                    selected = [groups[i] for i in indices if 0 <= i < len(groups)]
                except ValueError:
                    click.echo("❌ 输入无效，请输入数字（如 1,2,3）、'all' 或 'none'")
                    return

            # Add to config + throttle-join.
            for g in selected:
                link = f"https://t.me/{g['username']}" if g["username"] else str(g["id"])
                if link not in config.get("groups", []):
                    config.setdefault("groups", []).append(link)
                if g["username"]:
                    try:
                        await throttle.run_join(
                            g["username"],
                            lambda u=g["username"]: finder.join_group(u),
                        )
                    except DailyLimitExceeded:
                        click.echo("⏸️  Daily join limit hit; stopping.")
                        break

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            click.echo(f"✅ Added {len(selected)} groups to config.")


@cli.group(name="groups")
def groups_cmd():
    """Manage monitored groups."""
    pass


@cli.command(name="crawl-bot")
@click.option(
    "--bot",
    default=None,
    help="Override bot username (defaults to bot_search.bots[0] in config).",
)
@click.option(
    "--keywords",
    default="",
    help="Comma-separated queries; overrides products×actions matrix.",
)
@click.option(
    "--max-queries",
    default=None,
    type=int,
    help="Cap queries per run (default: bot_search.max_queries_per_run).",
)
@click.option(
    "--fetch-detail/--no-fetch-detail",
    default=None,
    help="Visit each preview deeplink to fetch the original message text. "
    "Default from bot_search.fetch_detail in config.",
)
def crawl_bot(bot, keywords, max_queries, fetch_detail):
    """Search a Telegram bot (e.g. @JISOU) for intel and harvest results."""
    asyncio.run(_crawl_bot_async(bot, keywords, max_queries, fetch_detail))


async def _crawl_bot_async(
    bot_override: str | None,
    keywords_arg: str,
    max_queries_override: int | None,
    fetch_detail_override: bool | None,
):
    logger = logging.getLogger("tg_crawler")
    config = load_config()
    bs_cfg = config.get("bot_search") or {}

    bots = list(bs_cfg.get("bots") or ["@JISOU"])
    if bot_override:
        bots = [bot_override if bot_override.startswith("@") else f"@{bot_override}"]
    if not bots:
        click.echo("❌ No bot configured. Add bot_search.bots in config.yaml.")
        return

    max_queries = (
        max_queries_override
        if max_queries_override is not None
        else int(bs_cfg.get("max_queries_per_run", 30))
    )
    interval = float(bs_cfg.get("query_interval_seconds", 10))
    convo_timeout = float(bs_cfg.get("conversation_timeout_seconds", 15))
    fetch_detail = (
        fetch_detail_override
        if fetch_detail_override is not None
        else bool(bs_cfg.get("fetch_detail", True))
    )
    detail_max_per_query = int(bs_cfg.get("detail_max_per_query", 20))
    detail_interval = float(bs_cfg.get("detail_interval_seconds", 1))

    # Build queries.
    qg = QueryGenerator(KEYWORDS_PATH)
    overrides = (
        [k.strip() for k in keywords_arg.split(",") if k.strip()]
        if keywords_arg
        else None
    )
    queries = qg.generate(max_queries=max_queries, override_keywords=overrides)
    if not queries:
        click.echo("❌ No queries generated. Check keywords.yaml or pass --keywords.")
        return

    click.echo(f"🤖 crawl-bot: bot={bots[0]}, queries={len(queries)}, fetch_detail={fetch_detail}")

    keyword_filter = KeywordFilter(str(KEYWORDS_PATH))
    llm_filter = LLMFilter(config["llm"])
    exporter = Exporter(
        output_dir=config["output"]["dir"],
        formats=config["output"]["format"],
    )
    extractor = GroupExtractor()
    candidate_pool = CandidatePool(_candidates_path(config))
    parser = BotResponseParser()
    query_throttle = BotQueryThrottle(
        interval_seconds=interval, max_queries_per_run=max_queries
    )

    all_records: list[IntelRecord] = []
    safe_re = __import__("re")

    async with TGClient(str(CONFIG_PATH)) as tg:
        client = tg.client

        # Pick the first reachable bot from the list (graceful fallback).
        chosen_bot: BotSearchClient | None = None
        for bot in bots:
            bsc = BotSearchClient(client, bot=bot, timeout=convo_timeout)
            try:
                await bsc.ensure_available()
                chosen_bot = bsc
                logger.info(f"Using bot: {bot}")
                break
            except BotUnavailable as e:
                logger.warning(f"Bot {bot} unavailable: {e}")
        if chosen_bot is None:
            click.echo("❌ No reachable bot.")
            return

        # Detail fetcher with its own throttle.
        detail_throttle = BotQueryThrottle(
            interval_seconds=detail_interval,
            max_queries_per_run=10_000,  # cap is per-query below, not per-run
        )
        detail_fetcher = DetailFetcher(client, throttle=detail_throttle) if fetch_detail else None

        for q in queries:
            try:
                await query_throttle.acquire()
            except BotQueryLimitExceeded:
                click.echo("⏸️  Query cap reached.")
                break

            reply = await chosen_bot.query(q)
            if reply is None:
                continue

            previews = parser.parse(reply, query=q, bot=bots[0])
            if not previews:
                continue

            # Always export raw (preview-level snapshot).
            safe_q = safe_re.sub(r"[^\w一-鿿]+", "_", q).strip("_")
            raw_dicts = [
                {
                    "bot": p.bot, "query": p.query,
                    "raw_line": p.raw_line, "text": p.text,
                    "deeplink": p.deeplink,
                    "channel_username": p.channel_username,
                    "msg_id": p.msg_id, "icon": p.icon,
                    "seen_at": p.seen_at.isoformat(),
                }
                for p in previews
            ]
            exporter.export_raw(
                raw_dicts,
                group_name=f"{bots[0].lstrip('@')}_{safe_q}",
                subdir="bot",
            )

            # Reverse-discovery: feed deeplinks into the candidate pool.
            class _M:
                """A MessageData-shaped shim so GroupExtractor accepts the line."""
                def __init__(self, p):
                    self.text = p.raw_line
                    self.group_name = f"bot:{bots[0]}"
                    self.msg_id = p.msg_id or 0
                    self.date = p.seen_at
                    self.forward_from_username = None
            signals = extractor.extract_from([_M(p) for p in previews])
            if signals:
                candidate_pool.merge(signals)
                candidate_pool.flush()

            # Build texts for LLM. With fetch_detail, visit each deeplink.
            texts: list[str] = []
            sources: list[tuple[BotPreviewLike, bool]] = []
            detail_count = 0
            detail_outcomes: dict[str, int] = {}  # reason → count
            for p in previews:
                full_text: str | None = None
                degraded = False
                if (
                    detail_fetcher is not None
                    and detail_count < detail_max_per_query
                    and p.channel_username and p.msg_id
                ):
                    outcome = await detail_fetcher.fetch(p)
                    detail_count += 1
                    detail_outcomes[outcome.reason or "unknown"] = (
                        detail_outcomes.get(outcome.reason or "unknown", 0) + 1
                    )
                    if outcome.success and outcome.full_text:
                        full_text = outcome.full_text
                    else:
                        degraded = True
                if not full_text:
                    full_text = p.text
                    degraded = True
                texts.append(
                    f"[preview-only] {full_text}" if degraded else full_text
                )
                sources.append((p, degraded))

            if detail_outcomes:
                summary = ", ".join(f"{k}={v}" for k, v in sorted(detail_outcomes.items()))
                logger.info(f"  detail-fetch: {summary}")

            # Keyword pre-filter to keep LLM cost in check.
            kept = [(t, p, deg) for t, (p, deg) in zip(texts, sources) if keyword_filter.matches(t)]
            if not kept:
                continue
            logger.info(f"  keyword filter: {len(kept)}/{len(previews)} for query={q!r}")

            results = await llm_filter.analyze([t for t, _, _ in kept])
            if len(results) != len(kept):
                logger.warning(
                    f"⚠️ LLM count mismatch on query {q!r} — got {len(results)}/{len(kept)}"
                )
                if not results:
                    continue

            for (text, p, degraded), result in zip(kept, results):
                if not result.is_relevant:
                    continue
                rec_id = (
                    f"bot_{p.channel_username}_{p.msg_id}"
                    if p.channel_username and p.msg_id
                    else f"bot_{bots[0].lstrip('@')}_{abs(hash((q, p.raw_line)))}"
                )
                all_records.append(IntelRecord(
                    id=rec_id,
                    source_group=f"bot:{bots[0]} q={q}",
                    date=p.seen_at,
                    sender_id=0,
                    sender_name="",
                    sender_username="",
                    original_text=text,
                    risk_type=result.risk_type,
                    risk_level=result.risk_level,
                    entities=result.entities,
                    summary=result.summary,
                    llm_model=config["llm"]["model"],
                    source_platform="bot",
                    source_url=p.deeplink or "",
                ))

    if all_records:
        exporter.export_filtered(all_records, file_suffix="bot")
        high = sum(1 for r in all_records if r.risk_level == "high")
        med = sum(1 for r in all_records if r.risk_level == "medium")
        low = sum(1 for r in all_records if r.risk_level == "low")
        click.echo(
            f"✅ crawl-bot done. Saved {len(all_records)} relevant records "
            f"(high={high}, medium={med}, low={low}) to ./output/filtered/intel_bot_*."
        )
    else:
        click.echo("ℹ️  crawl-bot done — no relevant records survived filters.")


# Type alias for the pipeline shim above.
BotPreviewLike = object


@cli.command(name="probe-bot-lookup")
@click.option("--sample-size", default=30, type=int,
              help="Total candidates to probe (capped by bot_search.max_queries_per_run).")
@click.option("--seed", default=42, type=int, help="RNG seed for reproducible sampling.")
@click.option("--bot", default=None,
              help="Override bot username (defaults to bot_search.bots[0]).")
@click.option("--report-dir", default="output/probe",
              help="Directory for the JSON + Markdown report.")
def probe_bot_lookup(sample_size: int, seed: int, bot, report_dir: str):
    """Probe how well the search bot reflects candidate-pool entries.

    Stratified-samples 30 candidates (5 per layer × 6 layers), queries the
    bot, classifies each reply, and writes a JSON + Markdown report.
    Read-only: never mutates the candidate pool.
    """
    asyncio.run(_probe_bot_lookup_async(sample_size, seed, bot, report_dir))


async def _probe_bot_lookup_async(
    sample_size: int, seed: int, bot_override: str | None, report_dir: str,
):
    from datetime import datetime, timezone

    logger = logging.getLogger("tg_crawler")
    config = load_config()
    bs_cfg = config.get("bot_search") or {}

    # Resolve bot list (same pattern as crawl-bot).
    bots = list(bs_cfg.get("bots") or ["@JISOU"])
    if bot_override:
        bots = [bot_override if bot_override.startswith("@") else f"@{bot_override}"]
    if not bots:
        click.echo("❌ No bot configured. Add bot_search.bots in config.yaml.")
        return

    interval = float(bs_cfg.get("query_interval_seconds", 10))
    convo_timeout = float(bs_cfg.get("conversation_timeout_seconds", 15))
    max_queries = int(bs_cfg.get("max_queries_per_run", 30))
    # The throttle's per-run cap should be at least sample_size, otherwise
    # the probe will truncate before finishing.
    cap = max(sample_size, max_queries)

    # Load candidate pool (read-only).
    pool = CandidatePool(_candidates_path(config))
    entries = pool.list_all()
    if not entries:
        click.echo("❌ Candidate pool is empty. Run `crawl` first.")
        return

    # Stratified sample.
    samples = Sampler(seed=seed).draw(entries, sample_size=sample_size)
    if not samples:
        click.echo("❌ Sampler returned 0 — check candidate pool.")
        return

    click.echo(
        f"🧪 probe-bot-lookup: sample={len(samples)}/{len(entries)} "
        f"seed={seed} bot={bots[0]}"
    )

    parser = BotResponseParser()
    throttle = BotQueryThrottle(
        interval_seconds=interval, max_queries_per_run=cap,
    )

    async with TGClient(str(CONFIG_PATH)) as tg:
        client = tg.client

        # Pick the first reachable bot (same fallback as crawl-bot).
        chosen_bot: BotSearchClient | None = None
        chosen_name: str = ""
        for b in bots:
            bsc = BotSearchClient(client, bot=b, timeout=convo_timeout)
            try:
                await bsc.ensure_available()
                chosen_bot = bsc
                chosen_name = b
                logger.info(f"Using bot: {b}")
                break
            except BotUnavailable as e:
                logger.warning(f"Bot {b} unavailable: {e}")
        if chosen_bot is None:
            click.echo("❌ No reachable bot.")
            return

        runner = ProbeRunner(
            bot_client=chosen_bot, parser=parser,
            throttle=throttle, bot_name=chosen_name,
        )
        records, truncated = await runner.run(samples)

    reporter = ProbeReporter(
        dest_dir=report_dir,
        bot=chosen_name,
        sample_size=len(samples),
        seed=seed,
        candidate_pool_total=len(entries),
        truncated=truncated,
        generated_at=datetime.now(timezone.utc),
    )
    json_path, md_path = reporter.write(records)
    click.echo(f"✅ wrote {json_path}")
    click.echo(f"✅ wrote {md_path}")
    if truncated:
        click.echo("⚠️  Run truncated — throttle cap hit before all samples completed.")


@cli.command(name="crawl-twitter")
@click.option(
    "--keywords",
    default="",
    help="Comma-separated extra search keywords (overrides config if provided)",
)
@click.option(
    "--users",
    default="",
    help="Comma-separated @screen_names to monitor (overrides config if provided)",
)
@click.option("--days", default=7, type=int, help="Only keep tweets newer than N days")
@click.option(
    "--max-pages",
    default=None,
    type=int,
    help="Override max pagination pages (default: from config)",
)
@click.option(
    "--search-type",
    default=None,
    type=click.Choice(["Latest", "Top"]),
    help="Search type (default: from config)",
)
def crawl_twitter(keywords: str, users: str, days: int, max_pages, search_type):
    """Crawl Twitter/X for ByteDance-related black/gray industry intel via tikhub.io."""
    asyncio.run(
        _crawl_twitter_async(
            keywords_arg=keywords,
            users_arg=users,
            days=days,
            max_pages_override=max_pages,
            search_type_override=search_type,
        )
    )


async def _crawl_twitter_async(
    keywords_arg: str,
    users_arg: str,
    days: int,
    max_pages_override,
    search_type_override,
):
    logger = logging.getLogger("tg_crawler")
    config = load_config()

    tw_cfg = config.get("twitter") or {}
    api_key = tw_cfg.get("api_key", "").strip()
    if not api_key:
        click.echo("❌ twitter.api_key not configured in config/config.yaml")
        return

    # CLI args override config
    if keywords_arg:
        keywords = [k.strip() for k in keywords_arg.split(",") if k.strip()]
    else:
        keywords = list(tw_cfg.get("search_keywords") or [])

    if users_arg:
        users = [u.strip().lstrip("@") for u in users_arg.split(",") if u.strip()]
    else:
        users = [u.strip().lstrip("@") for u in (tw_cfg.get("monitor_users") or [])]

    if not keywords and not users:
        click.echo(
            "❌ No keywords or users to crawl. Configure twitter.search_keywords / "
            "twitter.monitor_users or pass --keywords / --users."
        )
        return

    max_pages = max_pages_override if max_pages_override is not None else int(
        tw_cfg.get("max_pages", 5)
    )
    search_type = search_type_override or tw_cfg.get("search_type", "Latest")

    # Components
    rate_limiter = RateLimiter(
        delay_min=config["crawl"]["delay_min"],
        delay_max=config["crawl"]["delay_max"],
    )
    keyword_filter = KeywordFilter(str(KEYWORDS_PATH))
    llm_filter = LLMFilter(config["llm"])
    exporter = Exporter(
        output_dir=config["output"]["dir"],
        formats=config["output"]["format"],
        source="twitter",
    )

    all_tweets: list[TweetData] = []

    try:
        async with TwitterClient(
            api_key=api_key,
            base_url=tw_cfg.get("api_base", TwitterClient.DEFAULT_BASE_URL),
        ) as twitter:
            fetcher = TwitterFetcher(twitter, rate_limiter)

            for kw in keywords:
                tweets = await fetcher.search(
                    keyword=kw,
                    search_type=search_type,
                    max_pages=max_pages,
                    days=days,
                )
                all_tweets.extend(tweets)
                if tweets:
                    raw = [t.to_dict() for t in tweets]
                    exporter.export_raw(raw, group_name=f"search_{kw}", subdir="twitter")

            for handle in users:
                tweets = await fetcher.user_tweets(
                    screen_name=handle,
                    max_pages=max_pages,
                    days=days,
                )
                all_tweets.extend(tweets)
                if tweets:
                    raw = [t.to_dict() for t in tweets]
                    exporter.export_raw(raw, group_name=f"user_{handle}", subdir="twitter")
    except TikHubAuthError as e:
        click.echo(f"❌ tikhub authentication failed — check twitter.api_key: {e}")
        return

    if not all_tweets:
        logger.info("No tweets fetched.")
        return

    # De-duplicate by tweet_id (a single tweet may match multiple keywords)
    dedup: dict[str, TweetData] = {}
    for t in all_tweets:
        dedup.setdefault(t.tweet_id, t)
    tweets_unique = list(dedup.values())
    logger.info(f"📥 Total unique tweets fetched: {len(tweets_unique)}")

    # Keyword filter (products x actions)
    filtered_tweets: list[TweetData] = [
        t for t in tweets_unique if keyword_filter.matches(t.text)
    ]
    logger.info(
        f"🔍 Keyword filter: {len(filtered_tweets)}/{len(tweets_unique)} tweets passed"
    )
    if not filtered_tweets:
        return

    # LLM analysis
    logger.info(f"🤖 LLM analyzing {len(filtered_tweets)} tweets...")
    texts = [t.text for t in filtered_tweets]
    results = await llm_filter.analyze(texts)

    records: list[IntelRecord] = []
    for tweet, result in zip(filtered_tweets, results):
        if not result.is_relevant:
            continue
        records.append(
            IntelRecord(
                id=f"tweet_{tweet.tweet_id}",
                source_group=tweet.source_keyword or f"@{tweet.screen_name}",
                date=tweet.date,
                sender_id=int(tweet.user_id) if tweet.user_id.isdigit() else 0,
                sender_name=tweet.user_name,
                sender_username=tweet.screen_name,
                original_text=tweet.text,
                risk_type=result.risk_type,
                risk_level=result.risk_level,
                entities=result.entities,
                summary=result.summary,
                llm_model=config["llm"]["model"],
                source_platform="twitter",
                source_url=tweet.url,
            )
        )

    exporter.export_filtered(records, file_suffix="twitter")
    high = sum(1 for r in records if r.risk_level == "high")
    med = sum(1 for r in records if r.risk_level == "medium")
    low = sum(1 for r in records if r.risk_level == "low")
    logger.info(f"📊 Twitter intel: high={high}, medium={med}, low={low}")
    click.echo(
        f"✅ Done. Saved {len(records)} relevant tweets "
        f"(high={high}, medium={med}, low={low}) to ./output/filtered/"
    )


@cli.command(name="migrate-json")
def migrate_json():
    """Backfill existing output/raw + output/filtered JSON into intel.db.

    One-shot, idempotent. Use it to populate the SQLite store from the
    JSON archive you accumulated before SQLite existed. Re-running is safe —
    (day, id) dedupe prevents duplicates.
    """
    from tg_intel_crawler.storage.json_migrator import migrate_json_to_sqlite

    config = load_config()
    out_dir = config["output"]["dir"]
    click.echo(f"📦 Migrating JSON under {out_dir} → {out_dir}/intel.db ...")
    stats = migrate_json_to_sqlite(out_dir)
    click.echo(
        f"✅ Done.\n"
        f"  filtered: {stats['filtered_inserted']} rows inserted "
        f"from {stats['filtered_files']} file(s)\n"
        f"  raw:      {stats['raw_inserted']} rows inserted "
        f"from {stats['raw_files']} file(s)"
    )


@groups_cmd.command(name="list")
def groups_list():
    """List all configured groups."""
    config = load_config()
    groups = config.get("groups", [])
    if not groups:
        click.echo("No groups configured. Use 'discover' or 'groups add'.")
        return
    click.echo(f"Configured groups ({len(groups)}):")
    for i, g in enumerate(groups, 1):
        click.echo(f"  [{i}] {g}")


@groups_cmd.command(name="add")
@click.argument("link")
def groups_add(link: str):
    """Add a group link to monitoring list."""
    config = load_config()
    config.setdefault("groups", [])
    if link in config["groups"]:
        click.echo(f"Group already configured: {link}")
        return
    config["groups"].append(link)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    click.echo(f"✅ Added: {link}")


@groups_cmd.command(name="list-joined")
def groups_list_joined():
    """List groups/channels this account is currently in (read-only)."""
    asyncio.run(_groups_list_joined_async())


async def _groups_list_joined_async():
    config = load_config()
    discovery_cfg = config.get("discovery", {}) or {}

    async with TGClient(str(CONFIG_PATH)) as tg:
        scanner = JoinedGroupsScanner(tg.client)
        joined = await scanner.list_joined(
            include_channels=bool(discovery_cfg.get("scan_includes_channels", True))
        )

    if not joined:
        click.echo("No groups/channels found in this account.")
        return
    click.echo(f"Account is in {len(joined)} groups/channels:")
    for i, g in enumerate(joined, 1):
        members = f" — {g.members_count} members" if g.members_count else ""
        click.echo(f"  [{i}] {g.title} ({g.type}) {g.link}{members}")


@groups_cmd.command(name="sync")
def groups_sync():
    """Merge currently-joined groups into config.groups (no crawling)."""
    asyncio.run(_groups_sync_async())


async def _groups_sync_async():
    config = load_config()
    discovery_cfg = config.get("discovery", {}) or {}

    async with TGClient(str(CONFIG_PATH)) as tg:
        scanner = JoinedGroupsScanner(tg.client)
        joined = await scanner.list_joined(
            include_channels=bool(discovery_cfg.get("scan_includes_channels", True))
        )

    existing = list(config.get("groups", []) or [])
    seen = set(existing)
    added = []
    for g in joined:
        link = g.link
        if link not in seen:
            existing.append(link)
            seen.add(link)
            added.append(link)

    config["groups"] = existing
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    click.echo(f"✅ Synced {len(added)} new groups (total {len(existing)})")
    for link in added:
        click.echo(f"   + {link}")


# ---------------- candidates ----------------


@cli.group(name="candidates")
def candidates_cmd():
    """Manage discovered group candidates."""
    pass


@candidates_cmd.command(name="list")
@click.option(
    "--status",
    type=click.Choice(["pending", "approved", "rejected", "all"]),
    default="pending",
)
def candidates_list(status: str):
    """List candidates discovered from crawled messages."""
    config = load_config()
    pool = CandidatePool(_candidates_path(config))
    items = pool.list_all(status=None if status == "all" else status)

    if not items:
        click.echo(f"No candidates with status={status}.")
        return

    click.echo(f"{len(items)} candidate(s) [{status}]:\n")
    for c in sorted(items, key=lambda x: -x["count"]):
        click.echo(
            f"  {c['key']:<32} count={c['count']:<3} status={c['status']:<8} "
            f"first={c['first_seen'][:19]}"
        )


@candidates_cmd.command(name="approve")
@click.argument("keys", nargs=-1, required=True)
@click.option(
    "--no-join",
    is_flag=True,
    default=False,
    help="Only mark approved + add to config.groups; don't actually join now.",
)
def candidates_approve(keys, no_join: bool):
    """Approve candidates, join them (rate-limited), and add to config.groups."""
    asyncio.run(_candidates_approve_async(list(keys), no_join))


async def _candidates_approve_async(keys: list[str], no_join: bool):
    logger = logging.getLogger("tg_crawler")
    config = load_config()
    pool = CandidatePool(_candidates_path(config))
    changed = pool.approve(keys)
    if not changed:
        click.echo("Nothing changed (keys not found or already approved).")
        return

    pool.flush()
    click.echo(f"Approved {len(changed)} candidate(s): {', '.join(changed)}")

    # Append approved links to config.groups (dedupe).
    config.setdefault("groups", [])
    existing = set(config["groups"])
    for link in pool.approved_links():
        if link not in existing:
            config["groups"].append(link)
            existing.add(link)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    if no_join:
        click.echo("Skipping live join (--no-join).")
        return

    throttle = _make_join_throttle(config)
    async with TGClient(str(CONFIG_PATH)) as tg:
        # Warm up already-joined cache so we don't waste calls.
        scanner = JoinedGroupsScanner(tg.client)
        joined = await scanner.list_joined()
        throttle.warmup(
            usernames={g.username for g in joined if g.username},
            chat_ids={g.chat_id for g in joined},
        )

        finder = GroupFinder(tg.client)
        for key in changed:
            target = key if not key.startswith("+") else key  # GroupFinder handles links/usernames/+hash
            try:
                await throttle.run_join(target, lambda t=target: finder.join_group(t))
                click.echo(f"  ✅ joined {target}")
            except DailyLimitExceeded:
                click.echo(
                    f"  ⏸️  Daily join limit hit. Remaining will be re-tried "
                    f"next run (already approved & in config.groups)."
                )
                break
            except Exception as e:
                logger.warning(f"join {target} failed: {e}")
                click.echo(f"  ⚠️  {target} failed: {e}")


@candidates_cmd.command(name="reject")
@click.argument("keys", nargs=-1, required=True)
def candidates_reject(keys):
    """Reject candidates so they stay out of pending forever."""
    config = load_config()
    pool = CandidatePool(_candidates_path(config))
    changed = pool.reject(list(keys))
    pool.flush()
    if not changed:
        click.echo("Nothing changed.")
        return
    click.echo(f"Rejected {len(changed)} candidate(s): {', '.join(changed)}")


@candidates_cmd.command(name="stats")
def candidates_stats():
    """Print candidate-pool size by status."""
    config = load_config()
    pool = CandidatePool(_candidates_path(config))
    by_status: dict[str, int] = {}
    for c in pool.list_all():
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    if not by_status:
        click.echo("Candidate pool empty.")
        return
    for st, n in sorted(by_status.items()):
        click.echo(f"  {st:<10} {n}")
    click.echo(f"  {'total':<10} {sum(by_status.values())}")


@candidates_cmd.command(name="verify")
@click.option("--max", "max_candidates", default=80, type=int,
              help="Cap how many pending candidates to verify this run "
                   "(keep ≲100 to avoid Telegram FloodWait).")
@click.option("--interval", default=3.0, type=float,
              help="Seconds to wait between get_entity calls (anti-FloodWait).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Classify and report, but do not change any status.")
def candidates_verify(max_candidates: int, interval: float, dry_run: bool):
    """Verify pending candidates' real entity type via Telegram.

    Resolves each PUBLIC pending candidate with get_entity and marks the ones
    that are NOT groups/channels (personal accounts, bots, or unresolvable
    usernames) as ``rejected`` — keeping the candidate pool to actual groups.
    Private ``+hash`` candidates are groups by construction and are skipped.
    Rate-limited to avoid Telegram FloodWait.
    """
    asyncio.run(_candidates_verify_async(max_candidates, interval, dry_run))


async def _candidates_verify_async(
    max_candidates: int, interval: float, dry_run: bool,
):
    import asyncio as _asyncio

    from tg_intel_crawler.collector.entity_classifier import (
        EntityClassifier, EntityKind,
    )

    logger = logging.getLogger("tg_crawler")
    config = load_config()
    pool = CandidatePool(_candidates_path(config))

    # Only PUBLIC pending candidates need a type check; +hash are groups.
    pending = pool.list_all(status="pending")
    public = [c for c in pending if not c["key"].startswith("+")]
    private_count = len(pending) - len(public)
    # Highest-signal first so a capped run verifies the most-seen ones.
    public.sort(key=lambda c: -int(c.get("count", 0)))
    selected = public[:max_candidates]

    if not selected:
        click.echo(
            f"ℹ️  No public pending candidates to verify "
            f"({private_count} private +hash skipped)."
        )
        return

    click.echo(
        f"🔬 Verifying {len(selected)} of {len(public)} public pending "
        f"candidate(s) (interval={interval}s){' [dry-run]' if dry_run else ''}..."
    )

    counts = {"group": 0, "channel": 0, "user": 0, "bot": 0,
              "not_found": 0, "error": 0}
    to_reject: list[str] = []

    async with TGClient(str(CONFIG_PATH)) as tg:
        classifier = EntityClassifier(tg.client)
        flood_hit = False
        verified_n = 0
        for i, c in enumerate(selected):
            try:
                kind = await classifier.classify(c["key"])
            except Exception as e:
                # FloodWaitError (re-raised by the classifier) is a hard limit
                # — stop the whole run rather than hammering it.
                if type(e).__name__ == "FloodWaitError":
                    wait = int(getattr(e, "seconds", 0))
                    click.echo(
                        f"⏸️  Telegram FloodWait hit (~{wait}s / "
                        f"~{wait // 3600}h). Stopping after {verified_n} verified; "
                        f"rerun later for the rest."
                    )
                    flood_hit = True
                    break
                logger.warning("verify %s → unexpected error: %s", c["key"], e)
                counts["error"] += 1
                continue

            verified_n += 1
            counts[kind.value] = counts.get(kind.value, 0) + 1

            if kind.is_crawlable_group:
                pass  # keep
            elif kind is EntityKind.ERROR:
                # Transient (network) — don't reject, retry next run.
                logger.debug("verify %s → transient error, keeping", c["key"])
            else:
                # USER / BOT / NOT_FOUND → not a real group → reject.
                to_reject.append(c["key"])
                click.echo(f"  ⨯ {_candidate_link(c):<40} type={kind.value}")

            if interval > 0 and i < len(selected) - 1:
                await _asyncio.sleep(interval)

    # Apply rejections.
    rejected = []
    if to_reject and not dry_run:
        rejected = pool.reject(to_reject)
        pool.flush()

    # Summary.
    click.echo("")
    click.echo("📊 Verify Summary")
    click.echo(f"  Verified:   {verified_n} of {len(selected)} selected"
               f"{' (stopped early on FloodWait)' if flood_hit else ''}")
    click.echo(f"  ✅ groups/channels kept: {counts['group'] + counts['channel']} "
               f"(group={counts['group']}, channel={counts['channel']})")
    click.echo(f"  ⨯ non-groups: {counts['user'] + counts['bot'] + counts['not_found']} "
               f"(user={counts['user']}, bot={counts['bot']}, not_found={counts['not_found']})")
    if counts["error"]:
        click.echo(f"  ⚠️ transient errors (kept for retry): {counts['error']}")
    if dry_run:
        click.echo(f"  [dry-run] would reject {len(to_reject)} candidate(s); nothing changed.")
    else:
        click.echo(f"  Rejected:   {len(rejected)} candidate(s) → status=rejected")


@candidates_cmd.command(name="llm-review")
@click.option("--max-candidates", default=200, type=int,
              help="Cap candidates per run (top-N by score).")
@click.option("--stage1-batch-size", default=30, type=int,
              help="Stage 1 LLM batch size.")
@click.option("--write-config", is_flag=True, default=False,
              help="Promote llm_approved_high/medium to status=approved and "
                   "append to config.groups.")
@click.option("--auto-join", is_flag=True, default=False,
              help="Also limit-rate-join llm_approved_high candidates "
                   "(requires --write-config).")
@click.option("--force-rereview", is_flag=True, default=False,
              help="Re-review all pending candidates regardless of cache.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Run review but do not persist verdicts, status, or joins.")
@click.option("--include-private/--no-include-private", default=True,
              help="Include private (+hash) candidates (auto-downgraded one level).")
def candidates_llm_review(
    max_candidates, stage1_batch_size, write_config, auto_join,
    force_rereview, dry_run, include_private,
):
    """LLM-driven review of pending candidates → verdicts in yaml."""
    if auto_join and not write_config:
        raise click.UsageError("--auto-join requires --write-config")
    asyncio.run(_candidates_llm_review_async(
        max_candidates=max_candidates,
        stage1_batch_size=stage1_batch_size,
        write_config=write_config,
        auto_join=auto_join,
        force_rereview=force_rereview,
        dry_run=dry_run,
        include_private=include_private,
    ))


async def _candidates_llm_review_async(
    *,
    max_candidates: int,
    stage1_batch_size: int,
    write_config: bool,
    auto_join: bool,
    force_rereview: bool,
    dry_run: bool,
    include_private: bool,
):
    from datetime import datetime, timezone

    from tg_intel_crawler.collector.candidate_pool import CandidatePool
    from tg_intel_crawler.collector.client import TGClient
    from tg_intel_crawler.collector.group_finder import GroupFinder
    from tg_intel_crawler.collector.join_throttle import DailyLimitExceeded
    from tg_intel_crawler.collector.joined_scanner import JoinedGroupsScanner
    from tg_intel_crawler.filter.candidate_reviewer import (
        CandidateReviewer, Stage1Decision,
    )
    from tg_intel_crawler.storage.intel_stats import IntelStatsAggregator
    from tg_intel_crawler.storage.raw_lookup import RawMessageLookup

    logger = logging.getLogger("tg_crawler")
    config = load_config()
    out_dir = Path(config["output"]["dir"])

    pool = CandidatePool(_candidates_path(config))
    intel_stats = IntelStatsAggregator(str(out_dir / "filtered"))
    raw_lookup = RawMessageLookup(str(out_dir / "raw"))

    if not (out_dir / "raw").exists():
        click.echo("⚠️  output/raw/ missing — Stage 2 will rely on metadata only "
                   "and downgrade confidence.")
    if not (out_dir / "filtered").exists():
        click.echo("⚠️  output/filtered/ missing — source-group reputation will be empty.")

    # --- Pick candidates ---
    now = datetime.now(timezone.utc)
    pending = pool.pending_for_review(now=now, force_rereview=force_rereview)
    if not include_private:
        pending = [c for c in pending if not c["key"].startswith("+")]
    # Filter out empty-source candidates (no evidence at all).
    pending = [c for c in pending if c.get("sources")]

    def _score(c):
        sources = c.get("sources") or []
        max_high = max(
            (intel_stats.score_for(s.get("group", "")).get("high", 0) for s in sources),
            default=0,
        )
        return int(c.get("count", 0)) * max(max_high, 1)

    pending.sort(key=_score, reverse=True)
    selected = pending[:max_candidates]

    if not selected:
        click.echo("ℹ️  No candidates need review.")
        return

    click.echo(f"🔎 Reviewing {len(selected)} of {len(pending)} candidates "
               f"(max-candidates={max_candidates}).")

    reviewer = CandidateReviewer(
        llm_config=config["llm"],
        intel_stats=intel_stats,
        raw_lookup=raw_lookup,
    )

    # --- Stage 1 ---
    stage1_results = await reviewer.stage1_review(
        selected, batch_size=stage1_batch_size,
    )
    stage1_by_idx = {r.index: r for r in stage1_results}

    # --- Stage 2 (per candidate) ---
    counters = {
        "stage1_reject": 0, "stage1_advance": 0, "stage1_uncertain": 0,
        "stage2_approve_high": 0, "stage2_approve_medium": 0,
        "stage2_approve_low": 0, "stage2_reject": 0,
        "skipped_no_stage1": 0,
        "verdicts_written": 0,
    }

    for i, candidate in enumerate(selected):
        s1 = stage1_by_idx.get(i)
        if s1 is None:
            counters["skipped_no_stage1"] += 1
            continue

        if s1.decision is Stage1Decision.REJECT:
            counters["stage1_reject"] += 1
        elif s1.decision is Stage1Decision.ADVANCE:
            counters["stage1_advance"] += 1
        else:
            counters["stage1_uncertain"] += 1

        verdict = await reviewer.review_one(candidate, stage1=s1)
        if verdict is None:
            continue

        v_name = verdict["verdict"]
        if v_name == "llm_approved_high":
            counters["stage2_approve_high"] += 1
        elif v_name == "llm_approved_medium":
            counters["stage2_approve_medium"] += 1
        elif v_name == "llm_approved_low":
            counters["stage2_approve_low"] += 1
        elif v_name == "llm_rejected" and verdict["stage"] == 2:
            counters["stage2_reject"] += 1

        if not dry_run:
            pool.set_llm_verdict(candidate["key"], verdict)
            counters["verdicts_written"] += 1

    if not dry_run:
        pool.flush()

    # --- Optional: write_config + auto_join ---
    promoted = []
    joined_count = 0
    daily_limit_hit = False

    if not dry_run and write_config:
        promoted = pool.apply_llm_approvals()
        pool.flush()

        # append to config.groups (dedup)
        config.setdefault("groups", [])
        existing = set(config["groups"])
        for p in promoted:
            if p["link"] not in existing:
                config["groups"].append(p["link"])
                existing.add(p["link"])
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        if auto_join:
            high_only = [p for p in promoted if p["confidence"] == "high"]
            if high_only:
                throttle = _make_join_throttle(config)
                async with TGClient(str(CONFIG_PATH)) as tg:
                    scanner = JoinedGroupsScanner(tg.client)
                    joined = await scanner.list_joined()
                    throttle.warmup(
                        usernames={g.username for g in joined if g.username},
                        chat_ids={g.chat_id for g in joined},
                    )
                    finder = GroupFinder(tg.client)
                    for p in high_only:
                        target = p["key"]
                        try:
                            await throttle.run_join(
                                target, lambda t=target: finder.join_group(t),
                            )
                            joined_count += 1
                        except DailyLimitExceeded:
                            daily_limit_hit = True
                            break
                        except Exception as e:
                            logger.warning("auto-join %s failed: %s", target, e)

    # --- Summary ---
    click.echo("")
    click.echo("📊 LLM Review Summary")
    click.echo(f"  Reviewed:           {len(selected)} candidates "
               f"(out of {len(pending)} pending)")
    click.echo(f"  Stage 1 reject:     {counters['stage1_reject']}   → llm_rejected")
    click.echo(f"  Stage 1 advance:    {counters['stage1_advance']}   → Stage 2")
    click.echo(f"  Stage 1 uncertain:  {counters['stage1_uncertain']}   → Stage 2")
    s2_approve = (counters["stage2_approve_high"]
                  + counters["stage2_approve_medium"]
                  + counters["stage2_approve_low"])
    click.echo(f"  Stage 2 approve:    {s2_approve}   "
               f"(high={counters['stage2_approve_high']} / "
               f"medium={counters['stage2_approve_medium']} / "
               f"low={counters['stage2_approve_low']})")
    click.echo(f"  Stage 2 reject:     {counters['stage2_reject']}   → llm_rejected")
    if dry_run:
        click.echo("  [dry-run] no verdicts written, no status changed.")
    else:
        click.echo(f"  Verdicts written:   {counters['verdicts_written']}")
        if write_config:
            click.echo(f"  --write-config: appended {len(promoted)} links to config.groups")
        if auto_join:
            tail = " (hit daily_limit)" if daily_limit_hit else ""
            click.echo(f"  --auto-join:    joined {joined_count} groups{tail}")


@candidates_cmd.command(name="llm-crawl")
@click.option("--max-candidates", default=50, type=int,
              help="Cap candidates to review per run (top-N by score).")
@click.option("--stage1-batch-size", default=30, type=int,
              help="Stage 1 LLM batch size.")
@click.option("--stage2-concurrency", default=5, type=int,
              help="How many Stage 2 candidates to review in parallel.")
@click.option("--days", default=7, type=int,
              help="Days of history to crawl from each selected group.")
@click.option("--min-confidence", type=click.Choice(["high", "medium", "low"]),
              default="medium",
              help="Lowest LLM confidence whose groups will be crawled.")
@click.option("--max-crawl", default=10, type=int,
              help="Cap how many LLM-selected groups to actually crawl this run.")
@click.option("--include-private/--no-include-private", default=True,
              help="Include private (+hash) candidates (auto-downgraded one level).")
@click.option("--no-join", is_flag=True, default=False,
              help="Skip live join — only crawl groups already joinable/joined.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Run LLM selection only; do not join, crawl, or persist.")
def candidates_llm_crawl(
    max_candidates, stage1_batch_size, stage2_concurrency, days, min_confidence,
    max_crawl, include_private, no_join, dry_run,
):
    """Let the LLM pick promising candidates, then join + crawl them.

    Two-stage LLM review (same engine as ``llm-review``) selects groups whose
    confidence ≥ --min-confidence, rate-limit-joins them, fetches --days of
    history, and runs the full keyword → LLM → export intel pipeline. Selected
    candidates are marked approved and appended to config.groups.
    """
    asyncio.run(_candidates_llm_crawl_async(
        max_candidates=max_candidates,
        stage1_batch_size=stage1_batch_size,
        stage2_concurrency=stage2_concurrency,
        days=days,
        min_confidence=min_confidence,
        max_crawl=max_crawl,
        include_private=include_private,
        no_join=no_join,
        dry_run=dry_run,
    ))


async def _candidates_llm_crawl_async(
    *,
    max_candidates: int,
    stage1_batch_size: int,
    stage2_concurrency: int,
    days: int,
    min_confidence: str,
    max_crawl: int,
    include_private: bool,
    no_join: bool,
    dry_run: bool,
):
    from datetime import datetime, timezone

    from tg_intel_crawler.filter.candidate_reviewer import CandidateReviewer
    from tg_intel_crawler.storage.intel_stats import IntelStatsAggregator
    from tg_intel_crawler.storage.raw_lookup import RawMessageLookup

    logger = logging.getLogger("tg_crawler")
    config = load_config()
    out_dir = Path(config["output"]["dir"])

    pool = CandidatePool(_candidates_path(config))
    intel_stats = IntelStatsAggregator(str(out_dir / "filtered"))
    raw_lookup = RawMessageLookup(str(out_dir / "raw"))

    if not (out_dir / "raw").exists():
        click.echo("⚠️  output/raw/ missing — Stage 2 will rely on metadata only "
                   "and downgrade confidence.")

    # --- Pick candidates to review ---
    now = datetime.now(timezone.utc)
    pending = pool.pending_for_review(now=now, force_rereview=True)
    if not include_private:
        pending = [c for c in pending if not c["key"].startswith("+")]
    pending = [c for c in pending if c.get("sources")]

    def _score(c):
        sources = c.get("sources") or []
        max_high = max(
            (intel_stats.score_for(s.get("group", "")).get("high", 0) for s in sources),
            default=0,
        )
        return int(c.get("count", 0)) * max(max_high, 1)

    pending.sort(key=_score, reverse=True)
    selected = pending[:max_candidates]
    if not selected:
        click.echo("ℹ️  No candidates available to review. Run `crawl` first.")
        return

    click.echo(f"🔎 LLM reviewing {len(selected)} of {len(pending)} candidates "
               f"(min-confidence={min_confidence}, max-crawl={max_crawl}).")

    reviewer = CandidateReviewer(
        llm_config=config["llm"],
        intel_stats=intel_stats,
        raw_lookup=raw_lookup,
    )

    # --- Stage 1: cheap batched metadata triage ---
    click.echo(f"  Stage 1: triaging {len(selected)} candidates "
               f"in {(len(selected) + stage1_batch_size - 1) // stage1_batch_size} batch(es)...")
    stage1_results = await reviewer.stage1_review(
        selected, batch_size=stage1_batch_size,
    )
    stage1_by_idx = {r.index: r for r in stage1_results}

    conf_rank = {"high": 3, "medium": 2, "low": 1}
    threshold = conf_rank[min_confidence]

    # Only candidates that survived Stage 1 (have a result) go to Stage 2.
    stage2_targets = [
        (i, candidate)
        for i, candidate in enumerate(selected)
        if stage1_by_idx.get(i) is not None
    ]
    click.echo(f"  Stage 2: adjudicating {len(stage2_targets)} candidates "
               f"(concurrency={stage2_concurrency})...")

    # --- Stage 2: adjudicate concurrently with a bounded semaphore ---
    sem = asyncio.Semaphore(max(1, stage2_concurrency))
    done_count = 0
    total_s2 = len(stage2_targets)
    progress_lock = asyncio.Lock()

    async def _review(idx: int, candidate: dict):
        nonlocal done_count
        s1 = stage1_by_idx.get(idx)
        async with sem:
            verdict = await reviewer.review_one(candidate, stage1=s1)
        async with progress_lock:
            done_count += 1
            click.echo(f"    [{done_count}/{total_s2}] {_candidate_link(candidate)}")
        return candidate, verdict

    review_results = await asyncio.gather(
        *(_review(i, c) for i, c in stage2_targets)
    )

    chosen: list[dict] = []  # [{key, link, confidence, risk_type, reason}]
    for candidate, verdict in review_results:
        if verdict is None:
            continue
        if not dry_run:
            pool.set_llm_verdict(candidate["key"], verdict)
        v_name = verdict["verdict"]
        if not v_name.startswith("llm_approved_"):
            continue
        conf = verdict.get("confidence", "low")
        if conf_rank.get(conf, 0) < threshold:
            continue
        key = candidate["key"]
        link = _candidate_link(candidate)
        chosen.append({
            "key": key,
            "link": link,
            "confidence": conf,
            "risk_type": verdict.get("risk_type", ""),
            "reason": verdict.get("reason", ""),
        })

    if not dry_run:
        pool.flush()

    # Rank chosen by confidence (high first) and cap.
    chosen.sort(key=lambda c: -conf_rank.get(c["confidence"], 0))
    to_crawl = chosen[:max_crawl]

    if not to_crawl:
        click.echo(f"\n🤖 LLM selected 0 group(s) ≥ {min_confidence}. Nothing to do.")
        return

    # --- Build the crawl pipeline components (needed for both dry-run
    #     verification and the real crawl) ---
    rate_limiter = RateLimiter(
        delay_min=config["crawl"]["delay_min"],
        delay_max=config["crawl"]["delay_max"],
    )
    keyword_filter = KeywordFilter(str(KEYWORDS_PATH))
    llm_filter = LLMFilter(config["llm"])
    exporter = Exporter(
        output_dir=config["output"]["dir"],
        formats=config["output"]["format"],
    )
    extractor = GroupExtractor()

    throttle = _make_join_throttle(config)
    totals = {"relevant": 0, "high": 0, "medium": 0, "low": 0}
    crawled_keys: list[str] = []

    from tg_intel_crawler.collector.entity_classifier import EntityClassifier

    async with TGClient(str(CONFIG_PATH)) as tg:
        client = tg.client
        fetcher = MessageFetcher(client, rate_limiter)
        finder = GroupFinder(client)

        # Warm up already-joined cache so we don't waste join quota.
        scanner = JoinedGroupsScanner(client)
        joined = await scanner.list_joined()
        throttle.warmup(
            usernames={g.username for g in joined if g.username},
            chat_ids={g.chat_id for g in joined},
        )

        # --- Entity-type verification BEFORE we present anything ---
        # A bare @username mined from text could be a personal account or bot
        # (e.g. "联系 @clhs9 买号" / "@xz8568"), NOT a group. The LLM only judged
        # "worth monitoring", it did NOT (and cannot) judge entity type. So we
        # resolve each PUBLIC candidate's real kind via get_entity here, split
        # into real-groups vs. non-groups, and only THEN show the lists — so
        # the "groups" list is honestly groups. Private +hash are groups by
        # construction → no check needed.
        classifier = EntityClassifier(client)
        public = [c for c in to_crawl if not c["key"].startswith("+")]
        private = [c for c in to_crawl if c["key"].startswith("+")]

        if public:
            click.echo(f"🔬 Verifying entity type for {len(public)} public candidate(s)...")
        real_groups: list[dict] = []
        non_groups: list[dict] = []   # LLM-picked but not a group
        for c in public:
            kind = await classifier.classify(c["key"])
            c["entity_kind"] = kind.value
            if kind.is_crawlable_group:
                real_groups.append(c)
            else:
                non_groups.append(c)
        for c in private:
            c["entity_kind"] = "private"
        real_groups.extend(private)

        # --- Present: confirmed groups + (separately) the skipped non-groups ---
        click.echo("")
        click.echo(f"✅ Confirmed group(s) ≥ {min_confidence} (LLM-picked AND verified as group): "
                   f"{len(real_groups)}")
        for c in real_groups:
            click.echo(f"  • {c['link']:<40} confidence={c['confidence']:<6} "
                       f"{c['risk_type']} — {c['reason']}")
        if non_groups:
            click.echo("")
            click.echo(f"⨯ LLM-picked but NOT a group — skipped: {len(non_groups)}")
            for c in non_groups:
                click.echo(f"  • {c['link']:<40} type={c['entity_kind']:<8} "
                           f"(LLM said {c['confidence']}: {c['reason']})")

        if dry_run:
            click.echo("\n[dry-run] verification done; no join, no crawl, no persist.")
            return
        if not real_groups:
            click.echo("\nℹ️  No real groups to crawl after verification.")
            return

        # From here on we only ever touch confirmed groups.
        to_crawl = real_groups

        for c in to_crawl:
            key = c["key"]
            # Join first (unless skipped) so private/non-joined groups become
            # crawlable. Already-joined groups short-circuit inside the throttle.
            if not no_join:
                try:
                    await throttle.run_join(
                        key, lambda t=key: finder.join_group(t),
                    )
                except DailyLimitExceeded:
                    click.echo("⏸️  Daily join limit hit; stopping further joins. "
                               "Remaining selected groups stay approved for next run.")
                    break
                except Exception as e:
                    logger.warning("join %s failed: %s", key, e)
                    click.echo(f"  ⚠️  join {key} failed: {e}; skipping crawl.")
                    continue

            click.echo(f"📡 Crawling {c['link']} ...")
            try:
                stats = await _crawl_one_group(
                    c["link"],
                    days=days,
                    fetcher=fetcher,
                    keyword_filter=keyword_filter,
                    llm_filter=llm_filter,
                    exporter=exporter,
                    extractor=extractor,
                    candidate_pool=pool,
                    config=config,
                    logger=logger,
                )
            except Exception as e:
                logger.warning("crawl %s failed: %s", key, e)
                click.echo(f"  ⚠️  crawl {key} failed: {e}")
                continue

            crawled_keys.append(key)
            for k in totals:
                totals[k] += stats[k]

    # --- Persist: approve crawled candidates + append to config.groups ---
    if crawled_keys:
        pool.approve(crawled_keys)
        pool.flush()
        config.setdefault("groups", [])
        existing = set(config["groups"])
        for c in to_crawl:
            if c["key"] in crawled_keys and c["link"] not in existing:
                config["groups"].append(c["link"])
                existing.add(c["link"])
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    # --- Summary ---
    click.echo("")
    click.echo("📊 LLM Crawl Summary")
    click.echo(f"  Groups crawled:     {len(crawled_keys)}")
    click.echo(f"  Relevant records:   {totals['relevant']} "
               f"(high={totals['high']}, medium={totals['medium']}, low={totals['low']})")
    if crawled_keys:
        click.echo(f"  Approved + added to config.groups: {len(crawled_keys)}")


if __name__ == "__main__":
    cli()
