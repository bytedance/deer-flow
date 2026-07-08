"""
Context Manager — Session state & conversational memory for Agent BI.

This module enables natural follow-up conversations with data. Instead of
starting from scratch each time, the agent remembers what table you're
analyzing, what dimensions you're focused on, and can resolve references
like "上个月" or "和去年同期比呢" into concrete queries.

Core capabilities:
    Session State     — current table, dimensions, metrics, time range
    Query History     — what was asked, what was found
    Reference Resolution — "上个月" → specific date range
    Intent Detection  — is this a follow-up, refinement, or new question?
    Context Export    — generate prompt context for LLM consumption

Architecture:
    ContextManager → Session → Turn → ReferenceResolver + IntentDetector

Usage:
    from scripts.context_manager import ContextManager

    ctx = ContextManager()
    ctx.start_session("orders", db_path="workspace.duckdb")
    ctx.record_query("SELECT region, SUM(amount) FROM orders GROUP BY region")
    ctx.resolve("上个月呢？")  # → {refined_query, time_range, ...}
"""

import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

class TurnType(str, Enum):
    """Type of conversation turn."""
    QUERY = "query"             # SQL query
    CHART = "chart"             # Chart generation
    INSIGHT = "insight"         # Insight/analysis request
    REPORT = "report"           # Report generation
    FOLLOW_UP = "follow_up"     # Follow-up/refinement
    COMMAND = "command"         # System command (/start, /stop, etc.)
    UNKNOWN = "unknown"


class FollowUpIntent(str, Enum):
    """Detected intent of a follow-up question."""
    REFINE = "refine"           # Narrow down: "只看广东的数据"
    COMPARE = "compare"         # Compare: "和去年同期比"
    PIVOT = "pivot"             # Change dimension: "按渠道分析"
    DRILL_DOWN = "drill_down"   # Go deeper: "深挖一下白酒"
    EXPAND = "expand"           # Broaden: "看全年的"
    EXPLAIN = "explain"         # Ask why: "为什么下降了"
    PREDICT = "predict"         # Forecast: "预测下个月"
    RECAP = "recap"             # Recall: "刚才那个图表是什么"
    NEW_TOPIC = "new_topic"     # Completely new question


@dataclass
class TimeContext:
    """Temporal context from the current analysis."""
    column: str = ""                    # Date column name
    min_date: Optional[str] = None      # Earliest date in data
    max_date: Optional[str] = None      # Latest date in data
    granularity: str = "month"          # day, week, month, quarter, year
    current_focus_start: Optional[str] = None  # User's current time focus
    current_focus_end: Optional[str] = None


@dataclass
class AnalysisFocus:
    """What the user is currently analyzing."""
    dimensions: list[str] = field(default_factory=list)   # GROUP BY columns
    metrics: list[str] = field(default_factory=list)      # Metric columns
    filters: list[str] = field(default_factory=list)      # WHERE clauses
    sort_by: str = ""                                      # ORDER BY
    top_n: int = 0                                         # LIMIT


@dataclass
class Turn:
    """A single conversation turn."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    user_input: str = ""
    intent: TurnType = TurnType.UNKNOWN
    follow_up_intent: Optional[FollowUpIntent] = None
    sql_executed: str = ""
    result_summary: str = ""        # "86 rows, 3 columns"
    insight_ids: list[str] = field(default_factory=list)  # References to insights
    chart_type: str = ""
    chart_path: str = ""
    table_used: str = ""


@dataclass
class Session:
    """Complete analysis session state.

    Tracks everything the agent needs to know to maintain conversational
    continuity across multiple turns.
    """
    session_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Current analysis context
    current_table: str = ""
    current_db: str = "workspace.duckdb"
    time_context: TimeContext = field(default_factory=TimeContext)
    focus: AnalysisFocus = field(default_factory=AnalysisFocus)

    # History
    turns: list[Turn] = field(default_factory=list)
    last_query: str = ""
    last_result_columns: list[str] = field(default_factory=list)
    last_result_row_count: int = 0

    # Semantic model reference
    semantic_model_name: str = ""

    # Pinned insights (user bookmarked)
    pinned_insights: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_table": self.current_table,
            "current_db": self.current_db,
            "time_context": asdict(self.time_context),
            "focus": asdict(self.focus),
            "turns": [asdict(t) for t in self.turns],
            "last_query": self.last_query,
            "last_result_columns": self.last_result_columns,
            "last_result_row_count": self.last_result_row_count,
            "semantic_model_name": self.semantic_model_name,
            "pinned_insights": self.pinned_insights,
        }

    def get_recent_turns(self, n: int = 5) -> list[Turn]:
        """Get the most recent n turns."""
        return self.turns[-n:] if len(self.turns) >= n else self.turns[:]

    def get_last_turn(self) -> Optional[Turn]:
        """Get the most recent turn."""
        return self.turns[-1] if self.turns else None

    def is_active(self) -> bool:
        """Check if session has meaningful context."""
        return bool(self.current_table)


# ---------------------------------------------------------------------------
# Reference Resolver
# ---------------------------------------------------------------------------

class ReferenceResolver:
    """Resolves natural language references into concrete values.

    Handles time references ("上个月", "去年"), dimension references
    ("广东的", "白酒"), and metric references ("销售额").
    """

    # Time reference patterns → resolver functions
    TIME_PATTERNS = [
        (r"上个月|上月|前一个月", "last_month"),
        (r"去年|去年同期|上年", "last_year"),
        (r"上个季度|上季度", "last_quarter"),
        (r"本周|这周", "this_week"),
        (r"上周|上个星期", "last_week"),
        (r"本月|这个月", "this_month"),
        (r"今年|这一年", "this_year"),
        (r"最近(\d+)天", "last_n_days"),
        (r"最近(\d+)个月", "last_n_months"),
        (r"过去(\d+)天", "last_n_days"),
    ]

    # Comparison patterns
    COMPARE_PATTERNS = [
        (r"同比|和去年.*比|与去年.*比|较去年", "yoy"),
        (r"环比|和上月.*比|与上月.*比|较上月", "mom"),
        (r"对比|比较|vs|和.*对比", "compare"),
    ]

    # Drill-down patterns
    DRILL_PATTERNS = [
        (r"深挖|深入.*看|仔细.*看|具体.*看", "drill_down"),
        (r"只看|只看.*的|筛选|过滤", "filter"),
        (r"为什么|原因|怎么.*下降|怎么.*减少", "explain"),
    ]

    # Pivot patterns
    PIVOT_PATTERNS = [
        (r"换个角度|换个维度|按(.+)分析|按(.+)看|从(.+)看", "pivot"),
    ]

    def __init__(self):
        pass

    def resolve_time(
        self, text: str, time_context: TimeContext
    ) -> Optional[dict]:
        """Resolve time references in text to concrete date ranges.

        Args:
            text: User input text.
            time_context: Current temporal context from the session.

        Returns:
            Dict with start_date, end_date, granularity, or None.
        """
        for pattern, resolver_name in self.TIME_PATTERNS:
            m = re.search(pattern, text)
            if m:
                resolver = getattr(self, f"_resolve_{resolver_name}", None)
                if resolver:
                    result = resolver(m, time_context)
                    if result:
                        result["resolved_type"] = resolver_name
                        return result
        return None

    def resolve_dimension(self, text: str, focus: AnalysisFocus) -> Optional[str]:
        """Detect dimension references in text.

        Returns the dimension name if found, e.g., "广东" → "region".
        """
        # This is best-effort without semantic model context.
        # With semantic model, we could match values to columns.
        for dim in focus.dimensions:
            if dim in text:
                return dim
        return None

    def detect_comparison(self, text: str) -> Optional[str]:
        """Detect comparison intent."""
        for pattern, comp_type in self.COMPARE_PATTERNS:
            if re.search(pattern, text):
                return comp_type
        return None

    def detect_drill_intent(self, text: str) -> Optional[str]:
        """Detect drill-down/filter intent."""
        for pattern, intent in self.DRILL_PATTERNS:
            if re.search(pattern, text):
                return intent
        return None

    def detect_pivot(self, text: str) -> Optional[tuple[str, str]]:
        """Detect pivot intent. Returns (intent, new_dimension)."""
        for pattern, intent in self.PIVOT_PATTERNS:
            m = re.search(pattern, text)
            if m and m.lastindex:
                return (intent, m.group(1))
        return None

    # --- Private time resolvers ---

    def _resolve_last_month(self, match, tc: TimeContext) -> dict:
        today = datetime.now()
        end_of_last = today.replace(day=1) - timedelta(days=1)
        start_of_last = end_of_last.replace(day=1)
        return {
            "start_date": start_of_last.strftime("%Y-%m-%d"),
            "end_date": end_of_last.strftime("%Y-%m-%d"),
            "granularity": "day",
            "label": f"{start_of_last.strftime('%Y年%m月')}",
        }

    def _resolve_last_year(self, match, tc: TimeContext) -> dict:
        today = datetime.now()
        last_year = today.year - 1
        return {
            "start_date": f"{last_year}-01-01",
            "end_date": f"{last_year}-12-31",
            "granularity": "month",
            "label": f"{last_year}年",
        }

    def _resolve_last_quarter(self, match, tc: TimeContext) -> dict:
        today = datetime.now()
        current_q = (today.month - 1) // 3 + 1
        if current_q == 1:
            last_q_start_month = 10
            last_q_year = today.year - 1
        else:
            last_q_start_month = (current_q - 2) * 3 + 1
            last_q_year = today.year
        last_q_end_month = last_q_start_month + 2
        return {
            "start_date": f"{last_q_year}-{last_q_start_month:02d}-01",
            "end_date": f"{last_q_year}-{last_q_end_month:02d}-{self._month_days(last_q_year, last_q_end_month)}",
            "granularity": "week",
            "label": f"{last_q_year}年Q{(last_q_start_month-1)//3+1}",
        }

    def _resolve_this_week(self, match, tc: TimeContext) -> dict:
        today = datetime.now()
        start_of_week = today - timedelta(days=today.weekday())
        return {
            "start_date": start_of_week.strftime("%Y-%m-%d"),
            "end_date": today.strftime("%Y-%m-%d"),
            "granularity": "day",
            "label": "本周",
        }

    def _resolve_last_week(self, match, tc: TimeContext) -> dict:
        today = datetime.now()
        start_of_this_week = today - timedelta(days=today.weekday())
        start_of_last_week = start_of_this_week - timedelta(days=7)
        end_of_last_week = start_of_this_week - timedelta(days=1)
        return {
            "start_date": start_of_last_week.strftime("%Y-%m-%d"),
            "end_date": end_of_last_week.strftime("%Y-%m-%d"),
            "granularity": "day",
            "label": "上周",
        }

    def _resolve_this_month(self, match, tc: TimeContext) -> dict:
        today = datetime.now()
        return {
            "start_date": today.strftime("%Y-01-01"),
            "end_date": today.strftime("%Y-%m-%d"),
            "granularity": "month",
            "label": f"{today.year}年至今",
        }

    def _resolve_last_n_days(self, match, tc: TimeContext) -> dict:
        n = int(match.group(1))
        today = datetime.now()
        start = today - timedelta(days=n)
        return {
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": today.strftime("%Y-%m-%d"),
            "granularity": "day",
            "label": f"最近{n}天",
        }

    def _resolve_last_n_months(self, match, tc: TimeContext) -> dict:
        n = int(match.group(1))
        today = datetime.now()
        start = today - timedelta(days=n * 30)
        return {
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": today.strftime("%Y-%m-%d"),
            "granularity": "month",
            "label": f"最近{n}个月",
        }

    @staticmethod
    def _month_days(year: int, month: int) -> int:
        """Get number of days in a month."""
        if month == 12:
            return 31
        next_month = datetime(year, month, 1) + timedelta(days=32)
        return (next_month.replace(day=1) - timedelta(days=1)).day


# ---------------------------------------------------------------------------
# Intent Detector
# ---------------------------------------------------------------------------

class IntentDetector:
    """Detects the intent of a user message in context.

    Determines whether the input is a new question, a follow-up,
    a refinement, a comparison, etc.
    """

    # Keywords suggesting a NEW question (reset context)
    NEW_TOPIC_INDICATORS = [
        r"^分析", r"^展示", r"^导入", r"^导出", r"^帮我",
        r"^看看", r"^查", r"^统计", r"^/import", r"^/chart",
        r"^/query", r"^/analyze", r"^/dashboard", r"^/report",
        r"^/tables", r"^/export",
    ]

    # Keywords suggesting a FOLLOW-UP (use existing context)
    FOLLOW_UP_INDICATORS = [
        r"呢[？?]?$", r"比[呢吗]?", r"也", r"再", r"换",
        r"刚才", r"上次", r"之前", r"继续", r"接着",
        r"深挖", r"具体", r"详细",
    ]

    # Short inputs that are likely follow-ups
    SHORT_FOLLOW_UP_PATTERNS = [
        r"^那(.{1,10})呢[？?]?$",
        r"^(.{1,10})呢[？?]?$",
        r"^和(.+)比[呢吗]?[？?]?$",
    ]

    def __init__(self):
        self.resolver = ReferenceResolver()

    def detect(
        self, user_input: str, session: Session
    ) -> dict:
        """Detect the intent of user input given current session context.

        Args:
            user_input: Raw user input text.
            session: Current analysis session.

        Returns:
            Dict with:
                intent_type: TurnType
                follow_up_intent: FollowUpIntent (if follow-up)
                is_new_topic: bool
                confidence: float 0-1
                resolved_time: dict or None
                suggested_action: str
        """
        result = {
            "intent_type": TurnType.UNKNOWN,
            "follow_up_intent": None,
            "is_new_topic": True,
            "confidence": 0.5,
            "resolved_time": None,
            "suggested_action": "clarify",
        }

        text = user_input.strip()

        # Check for explicit commands
        if text.startswith("/"):
            result["intent_type"] = TurnType.COMMAND
            result["is_new_topic"] = True
            result["confidence"] = 0.95
            result["suggested_action"] = "execute_command"
            return result

        # If no active session, it's always a new topic
        if not session.is_active():
            result["intent_type"] = self._classify_new_topic(text)
            result["is_new_topic"] = True
            result["confidence"] = 0.8
            result["suggested_action"] = "start_new_analysis"
            return result

        # Check if it's clearly a new topic
        if self._is_new_topic(text):
            result["intent_type"] = self._classify_new_topic(text)
            result["is_new_topic"] = True
            result["confidence"] = 0.85
            result["suggested_action"] = "start_new_analysis"
            return result

        # Check if it's a follow-up
        follow_up = self._detect_follow_up(text, session)
        if follow_up:
            result.update(follow_up)
            return result

        # Default: treat as new topic
        result["intent_type"] = self._classify_new_topic(text)
        result["is_new_topic"] = True
        result["confidence"] = 0.6
        result["suggested_action"] = "start_new_analysis"
        return result

    def _is_new_topic(self, text: str) -> bool:
        """Check if text suggests starting a new topic."""
        for pattern in self.NEW_TOPIC_INDICATORS:
            if re.search(pattern, text):
                return True
        return False

    def _classify_new_topic(self, text: str) -> TurnType:
        """Classify what kind of new topic this is."""
        if re.search(r"分析|洞察|发现|规律", text):
            return TurnType.INSIGHT
        if re.search(r"报告|总结|出报告", text):
            return TurnType.REPORT
        if re.search(r"图表|画|展示|可视化|chart|plot", text):
            return TurnType.CHART
        if re.search(r"select|查询|统计|group by|where", text, re.IGNORECASE):
            return TurnType.QUERY
        return TurnType.UNKNOWN

    def _detect_follow_up(self, text: str, session: Session) -> Optional[dict]:
        """Detect if text is a follow-up to the current session."""
        result = {
            "intent_type": TurnType.FOLLOW_UP,
            "follow_up_intent": None,
            "is_new_topic": False,
            "confidence": 0.5,
            "resolved_time": None,
            "suggested_action": "clarify",
        }

        # Try time reference resolution
        time_ref = self.resolver.resolve_time(text, session.time_context)
        if time_ref:
            result["resolved_time"] = time_ref
            result["confidence"] = 0.8

        # Detect comparison intent
        comp = self.resolver.detect_comparison(text)
        if comp:
            result["follow_up_intent"] = FollowUpIntent.COMPARE
            result["confidence"] = 0.85
            result["suggested_action"] = "generate_comparison"
            return result

        # Detect drill-down
        drill = self.resolver.detect_drill_intent(text)
        if drill:
            if drill == "explain":
                result["follow_up_intent"] = FollowUpIntent.EXPLAIN
                result["suggested_action"] = "explain_change"
            else:
                result["follow_up_intent"] = FollowUpIntent.DRILL_DOWN
                result["suggested_action"] = "apply_filter_or_drill"
            result["confidence"] = 0.75
            return result

        # Detect pivot
        pivot = self.resolver.detect_pivot(text)
        if pivot:
            result["follow_up_intent"] = FollowUpIntent.PIVOT
            result["confidence"] = 0.8
            result["suggested_action"] = "change_dimension"
            return result

        # Short follow-up patterns
        for pattern in self.SHORT_FOLLOW_UP_PATTERNS:
            if re.match(pattern, text):
                result["follow_up_intent"] = FollowUpIntent.REFINE
                result["confidence"] = 0.7
                result["suggested_action"] = "refine_analysis"
                return result

        # General follow-up indicators
        for pattern in self.FOLLOW_UP_INDICATORS:
            if re.search(pattern, text):
                result["follow_up_intent"] = FollowUpIntent.REFINE
                result["confidence"] = 0.6
                result["suggested_action"] = "continue_analysis"
                return result

        # If time was resolved but no specific follow-up intent detected
        if time_ref:
            result["follow_up_intent"] = FollowUpIntent.REFINE
            result["suggested_action"] = "refine_time_range"
            return result

        return None


# ---------------------------------------------------------------------------
# Context Manager
# ---------------------------------------------------------------------------

class ContextManager:
    """Manages analysis session lifecycle and conversational context.

    This is the central controller for conversational BI. It maintains
    session state across turns, resolves natural language references,
    and generates prompt context for LLM agents.

    Attributes:
        db_path: Path to the SQLite database for session storage.
        sessions: In-memory cache of active sessions.
        resolver: ReferenceResolver instance.
        detector: IntentDetector instance.
    """

    SESSION_DB = "outputs/.session_state.db"

    def __init__(self, session_db: str = SESSION_DB):
        """Initialize the context manager.

        Args:
            session_db: Path to SQLite session database.
        """
        self.session_db = session_db
        self.sessions: dict[str, Session] = {}
        self.resolver = ReferenceResolver()
        self.detector = IntentDetector()
        self._init_db()
        self._load_recent()

    # ------------------------------------------------------------------
    # Session Lifecycle
    # ------------------------------------------------------------------

    def start_session(
        self,
        table: str,
        db_path: str = "workspace.duckdb",
        dimensions: Optional[list[str]] = None,
        metrics: Optional[list[str]] = None,
        date_column: Optional[str] = None,
        semantic_model_name: str = "",
    ) -> Session:
        """Start a new analysis session.

        Args:
            table: Primary table to analyze.
            db_path: Database path.
            dimensions: Initial dimension columns.
            metrics: Initial metric columns.
            date_column: Date column name.
            semantic_model_name: Associated semantic model.

        Returns:
            A new Session object.
        """
        session = Session(
            current_table=table,
            current_db=db_path,
            semantic_model_name=semantic_model_name,
        )

        if dimensions:
            session.focus.dimensions = dimensions
        if metrics:
            session.focus.metrics = metrics

        # Auto-populate time context from Insight Engine profile
        if date_column or not date_column:
            self._enrich_time_context(session, date_column)

        self.sessions[session.session_id] = session
        self._save_session(session)
        logger.info("会话已创建", session_id=session.session_id, table=table)
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        if session_id in self.sessions:
            return self.sessions[session_id]
        session = self._load_session(session_id)
        if session:
            self.sessions[session_id] = session
        return session

    def get_latest_session(self) -> Optional[Session]:
        """Get the most recently updated session."""
        if not self.sessions:
            return None
        return max(self.sessions.values(), key=lambda s: s.updated_at)

    def end_session(self, session_id: str) -> bool:
        """End and archive a session."""
        if session_id in self.sessions:
            self.sessions.pop(session_id)
            self._delete_session(session_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Turn Recording
    # ------------------------------------------------------------------

    def record_turn(
        self,
        session: Session,
        user_input: str,
        intent: Optional[dict] = None,
        sql: str = "",
        result_summary: str = "",
        chart_type: str = "",
        chart_path: str = "",
        insight_ids: Optional[list[str]] = None,
    ) -> Turn:
        """Record a conversation turn in the session.

        Args:
            session: Current session.
            user_input: Raw user input.
            intent: Detected intent dict from IntentDetector.
            sql: SQL executed (if any).
            result_summary: Summary of results.
            chart_type: Chart type generated (if any).
            chart_path: Path to chart file (if any).
            insight_ids: IDs of generated insights.

        Returns:
            The recorded Turn.
        """
        if intent is None:
            intent = self.detector.detect(user_input, session)

        turn = Turn(
            user_input=user_input,
            intent=intent.get("intent_type", TurnType.UNKNOWN),
            follow_up_intent=intent.get("follow_up_intent"),
            sql_executed=sql,
            result_summary=result_summary,
            chart_type=chart_type,
            chart_path=chart_path,
            insight_ids=insight_ids or [],
            table_used=session.current_table,
        )

        session.turns.append(turn)
        if sql:
            session.last_query = sql
        session.updated_at = datetime.now().isoformat()

        self._save_session(session)
        return turn

    def record_insight(
        self,
        session: Session,
        insights: list,  # list of Insight objects
    ):
        """Record generated insights in the session."""
        ids = []
        for ins in insights:
            ins_id = f"{ins.type.value}_{len(session.turns)}_{len(ids)}"
            ids.append(ins_id)
        session.updated_at = datetime.now().isoformat()
        self._save_session(session)

    # ------------------------------------------------------------------
    # Context Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        user_input: str,
        session: Optional[Session] = None,
    ) -> dict:
        """Resolve a user message within session context.

        This is the main entry point for understanding what the user
        wants given the conversation history.

        Args:
            user_input: Raw user text.
            session: Current session (uses latest if None).

        Returns:
            Resolution dict with:
                intent: detected intent info
                time_range: resolved time range (if any)
                suggested_sql: suggested SQL fragment (if applicable)
                context_prompt: prompt context for LLM
                is_follow_up: bool
        """
        if session is None:
            session = self.get_latest_session()

        result = {
            "intent": None,
            "time_range": None,
            "suggested_sql_fragment": "",
            "context_prompt": "",
            "is_follow_up": False,
            "session_active": session.is_active() if session else False,
        }

        if session is None or not session.is_active():
            result["intent"] = self.detector.detect(user_input, Session())
            return result

        # Detect intent
        intent = self.detector.detect(user_input, session)
        result["intent"] = intent
        result["is_follow_up"] = not intent["is_new_topic"]

        # Resolve time references
        time_ref = self.resolver.resolve_time(user_input, session.time_context)
        if time_ref:
            result["time_range"] = time_ref
            # Build WHERE clause fragment
            if session.time_context.column:
                col = session.time_context.column
                col = session.time_context.column
                start = time_ref["start_date"]
                end = time_ref["end_date"]
                result["suggested_sql_fragment"] = (
                    f'"{col}" BETWEEN \'{start}\' AND \'{end}\''
                )

        # Build context prompt for LLM
        result["context_prompt"] = self._build_context_prompt(session, intent)

        return result

    def resolve_follow_up(
        self,
        user_input: str,
        session: Session,
    ) -> dict:
        """Specifically resolve a follow-up question.

        Returns enriched context for generating the follow-up query/chart.
        """
        resolution = self.resolve(user_input, session)

        # For comparison intents, generate comparison SQL
        if resolution["intent"].get("follow_up_intent") == FollowUpIntent.COMPARE:
            comp_type = self.resolver.detect_comparison(user_input)
            resolution["comparison_type"] = comp_type
            if comp_type == "yoy" and session.last_query:
                # Generate YoY comparison
                resolution["suggested_action"] = "add_yoy_comparison"
            elif comp_type == "mom" and session.last_query:
                resolution["suggested_action"] = "add_mom_comparison"

        # For drill-down, extract the drill target
        if resolution["intent"].get("follow_up_intent") == FollowUpIntent.DRILL_DOWN:
            # Try to extract what to drill into
            for dim in session.focus.dimensions:
                if dim in user_input:
                    resolution["drill_dimension"] = dim
                    break

        return resolution

    # ------------------------------------------------------------------
    # Prompt Context Generation
    # ------------------------------------------------------------------

    def get_prompt_context(self, session: Optional[Session] = None) -> str:
        """Generate a compact context block for injection into LLM prompts.

        Args:
            session: Session to generate context for (latest if None).

        Returns:
            Markdown-formatted context string.
        """
        if session is None:
            session = self.get_latest_session()
        if session is None or not session.is_active():
            return ""

        return self._build_context_prompt(session)

    def _build_context_prompt(
        self, session: Session, intent: Optional[dict] = None
    ) -> str:
        """Build the full LLM context prompt."""
        lines = []

        lines.append("## 当前分析会话\n")

        # Current focus
        lines.append(f"**分析表**: `{session.current_table}` ({session.current_db})")

        if session.time_context.column:
            tc = session.time_context
            lines.append(f"**时间列**: {tc.column}")
            if tc.min_date and tc.max_date:
                lines.append(f"**时间范围**: {tc.min_date[:10]} ~ {tc.max_date[:10]}")
            if tc.current_focus_start:
                lines.append(f"**当前聚焦**: {tc.current_focus_start} ~ {tc.current_focus_end or '至今'}")

        if session.focus.dimensions:
            lines.append(f"**分析维度**: {', '.join(session.focus.dimensions)}")
        if session.focus.metrics:
            lines.append(f"**分析指标**: {', '.join(session.focus.metrics)}")
        if session.focus.filters:
            lines.append(f"**已应用筛选**: {' AND '.join(session.focus.filters)}")

        # Recent history
        recent = session.get_recent_turns(5)
        if recent:
            lines.append("\n### 最近对话")
            for i, turn in enumerate(recent[-5:], 1):
                summary = turn.result_summary or turn.user_input[:50]
                lines.append(f"{i}. 用户: _{turn.user_input[:80]}_")
                if turn.sql_executed:
                    lines.append(f"   SQL: `{turn.sql_executed[:100]}{'...' if len(turn.sql_executed) > 100 else ''}`")
                if turn.chart_type:
                    lines.append(f"   图表: {turn.chart_type} → {turn.chart_path}")

        # Last query for reference
        if session.last_query:
            lines.append(f"\n**上一条SQL**: `{session.last_query[:200]}`")

        # Semantic model hint
        if session.semantic_model_name:
            lines.append(f"\n**语义模型**: {session.semantic_model_name}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Focus Management
    # ------------------------------------------------------------------

    def set_focus(
        self,
        session: Session,
        dimensions: Optional[list[str]] = None,
        metrics: Optional[list[str]] = None,
        filters: Optional[list[str]] = None,
        time_start: Optional[str] = None,
        time_end: Optional[str] = None,
    ):
        """Update the analysis focus within a session.

        Args:
            session: Session to update.
            dimensions: New dimension columns.
            metrics: New metric columns.
            filters: New filter conditions.
            time_start: Focus start date.
            time_end: Focus end date.
        """
        if dimensions is not None:
            session.focus.dimensions = dimensions
        if metrics is not None:
            session.focus.metrics = metrics
        if filters is not None:
            session.focus.filters = filters
        if time_start:
            session.time_context.current_focus_start = time_start
        if time_end:
            session.time_context.current_focus_end = time_end

        session.updated_at = datetime.now().isoformat()
        self._save_session(session)

    def pin_insight(self, session: Session, insight: dict):
        """Pin an insight for later reference."""
        session.pinned_insights.append(insight)
        session.updated_at = datetime.now().isoformat()
        self._save_session(session)

    # ------------------------------------------------------------------
    # Private: Persistence
    # ------------------------------------------------------------------

    def _init_db(self):
        """Initialize the SQLite session database."""
        os.makedirs(os.path.dirname(self.session_db), exist_ok=True)
        conn = sqlite3.connect(self.session_db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _save_session(self, session: Session):
        """Persist a session to SQLite."""
        conn = sqlite3.connect(self.session_db)
        conn.execute(
            """INSERT OR REPLACE INTO sessions (session_id, data, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            (session.session_id, json.dumps(session.to_dict(), ensure_ascii=False),
             session.created_at, session.updated_at),
        )
        conn.commit()
        conn.close()

    def _load_session(self, session_id: str) -> Optional[Session]:
        """Load a session from SQLite."""
        conn = sqlite3.connect(self.session_db)
        row = conn.execute(
            "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        conn.close()
        if row:
            return self._deserialize_session(json.loads(row[0]))
        return None

    def _load_recent(self):
        """Load recent sessions into memory."""
        conn = sqlite3.connect(self.session_db)
        rows = conn.execute(
            "SELECT data FROM sessions ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
        conn.close()
        for row in rows:
            try:
                session = self._deserialize_session(json.loads(row[0]))
                self.sessions[session.session_id] = session
            except Exception as e:
                logger.warning("会话加载失败", error=str(e))

    def _delete_session(self, session_id: str):
        """Delete a session from SQLite."""
        conn = sqlite3.connect(self.session_db)
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def _deserialize_session(self, data: dict) -> Session:
        """Deserialize session from dict."""
        session = Session(
            session_id=data.get("session_id", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            current_table=data.get("current_table", ""),
            current_db=data.get("current_db", "workspace.duckdb"),
            last_query=data.get("last_query", ""),
            last_result_columns=data.get("last_result_columns", []),
            last_result_row_count=data.get("last_result_row_count", 0),
            semantic_model_name=data.get("semantic_model_name", ""),
            pinned_insights=data.get("pinned_insights", []),
        )

        # Restore time context
        tc = data.get("time_context", {})
        session.time_context = TimeContext(
            column=tc.get("column", ""),
            min_date=tc.get("min_date"),
            max_date=tc.get("max_date"),
            granularity=tc.get("granularity", "month"),
            current_focus_start=tc.get("current_focus_start"),
            current_focus_end=tc.get("current_focus_end"),
        )

        # Restore focus
        fc = data.get("focus", {})
        session.focus = AnalysisFocus(
            dimensions=fc.get("dimensions", []),
            metrics=fc.get("metrics", []),
            filters=fc.get("filters", []),
            sort_by=fc.get("sort_by", ""),
            top_n=fc.get("top_n", 0),
        )

        # Restore turns
        for t_data in data.get("turns", []):
            turn = Turn(
                timestamp=t_data.get("timestamp", ""),
                user_input=t_data.get("user_input", ""),
                intent=TurnType(t_data.get("intent", "unknown")),
                sql_executed=t_data.get("sql_executed", ""),
                result_summary=t_data.get("result_summary", ""),
                insight_ids=t_data.get("insight_ids", []),
                chart_type=t_data.get("chart_type", ""),
                chart_path=t_data.get("chart_path", ""),
                table_used=t_data.get("table_used", ""),
            )
            fu = t_data.get("follow_up_intent")
            if fu:
                turn.follow_up_intent = FollowUpIntent(fu)
            session.turns.append(turn)

        return session

    def _enrich_time_context(self, session: Session, date_column: Optional[str] = None):
        """Auto-populate time context from database profiling."""
        try:
            from scripts.insight_engine import InsightEngine
            engine = InsightEngine(session.current_db)
            profile = engine.profile_table(session.current_table)
            if profile and profile.date_columns:
                dc_name = date_column or profile.date_columns[0]
                dc = next((c for c in profile.columns if c.name == dc_name), None)
                if dc:
                    session.time_context = TimeContext(
                        column=dc_name,
                        min_date=dc.min_date,
                        max_date=dc.max_date,
                        granularity=engine._detect_time_granularity(
                            session.current_table, dc_name
                        ),
                    )
        except Exception as e:
            logger.debug("时间上下文自动填充失败", error=str(e))


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def main():
    """CLI for context manager — session management and reference testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Context Manager — Conversational memory for Agent BI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/context_manager.py start orders --db workspace.duckdb
  python scripts/context_manager.py resolve "上个月呢？"
  python scripts/context_manager.py history
  python scripts/context_manager.py context
  python scripts/context_manager.py list
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # start command
    start_parser = subparsers.add_parser("start", help="Start a new analysis session")
    start_parser.add_argument("table", help="Table name")
    start_parser.add_argument("--db", default="workspace.duckdb", help="Database path")
    start_parser.add_argument("--dimensions", "-d", help="Comma-separated dimensions")
    start_parser.add_argument("--metrics", "-m", help="Comma-separated metrics")
    start_parser.add_argument("--date-column", help="Date column")
    start_parser.add_argument("--semantic-model", "-s", help="Semantic model name")

    # resolve command
    resolve_parser = subparsers.add_parser("resolve", help="Resolve a follow-up message")
    resolve_parser.add_argument("text", help="User input text")
    resolve_parser.add_argument("--session-id", help="Session ID (uses latest if omitted)")

    # history command
    subparsers.add_parser("history", help="Show session conversation history")

    # context command
    context_parser = subparsers.add_parser("context", help="Show current session context prompt")
    context_parser.add_argument("--session-id", help="Session ID (uses latest if omitted)")

    # list command
    subparsers.add_parser("list", help="List saved sessions")

    args = parser.parse_args()
    mgr = ContextManager()

    if args.command == "start":
        dims = args.dimensions.split(",") if args.dimensions else None
        mets = args.metrics.split(",") if args.metrics else None
        session = mgr.start_session(
            args.table,
            db_path=args.db,
            dimensions=dims,
            metrics=mets,
            date_column=args.date_column,
            semantic_model_name=args.semantic_model or "",
        )
        print(f"✅ 会话已创建: {session.session_id}")
        print(f"   表: {session.current_table}")
        if session.time_context.column:
            print(f"   时间范围: {session.time_context.min_date} ~ {session.time_context.max_date}")

    elif args.command == "resolve":
        session = None
        if args.session_id:
            session = mgr.get_session(args.session_id)
        result = mgr.resolve(args.text, session)
        if result["session_active"]:
            print(f"📝 输入: {args.text}")
            intent = result["intent"]
            print(f"   意图: {intent.get('intent_type', 'unknown')}")
            if intent.get("follow_up_intent"):
                print(f"   追问类型: {intent['follow_up_intent']}")
            if result.get("time_range"):
                tr = result["time_range"]
                print(f"   时间解析: {tr.get('label')} ({tr.get('start_date')} ~ {tr.get('end_date')})")
            if result.get("suggested_sql_fragment"):
                print(f"   SQL片段: {result['suggested_sql_fragment']}")
            print(f"\n{result.get('context_prompt', '')}")
        else:
            print(f"📝 输入: {args.text}")
            print("   ⚠️ 无活跃会话，建议先 /analyze <表名> 开始分析")

    elif args.command == "history":
        session = mgr.get_latest_session()
        if session and session.turns:
            print(f"\n📜 会话历史: {session.session_id}")
            print(f"   表: {session.current_table}")
            print(f"   共 {len(session.turns)} 轮对话\n")
            for i, turn in enumerate(session.turns, 1):
                print(f"  {i}. [{turn.intent.value}] {turn.user_input[:80]}")
                if turn.sql_executed:
                    print(f"     SQL: {turn.sql_executed[:120]}")
        else:
            print("📭 无会话历史")

    elif args.command == "context":
        session = None
        if args.session_id:
            session = mgr.get_session(args.session_id)
        ctx = mgr.get_prompt_context(session)
        if ctx:
            print(ctx)
        else:
            print("📭 无活跃会话")

    elif args.command == "list":
        if mgr.sessions:
            print(f"\n📊 共 {len(mgr.sessions)} 个会话:\n")
            for sid, s in mgr.sessions.items():
                print(f"  {sid}: {s.current_table} ({len(s.turns)} turns) — {s.updated_at[:19]}")
        else:
            print("📭 无保存的会话")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
