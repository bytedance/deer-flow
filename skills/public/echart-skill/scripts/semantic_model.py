"""
Semantic Model — Business-aware data modeling layer.

This module upgrades the simple metrics system into a full semantic layer
that defines business models, column metadata, metric calculations, and
table relationships. It's the foundation for natural-language-to-SQL,
intelligent chart recommendations, and contextual analysis.

Key concepts:
    Business Model — A business entity mapped to one or more database tables
    Column Def    — Semantic metadata for each column (type, description, role)
    Metric        — A named business metric with its SQL expression
    Relationship  — JOIN rules between business models

Architecture:
    SemanticModel → ModelManager → CLI (/semantic) + Python API

Usage:
    from scripts.semantic_model import SemanticModel, ModelManager

    mgr = ModelManager()
    model = mgr.create_from_table("sales", db_path="workspace.duckdb")
    mgr.save(model, "sales_model")
    # Now AI agents can understand what "总销售额" means and which column it maps to
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

class ColumnRole(str, Enum):
    """Semantic role of a column in the business model."""
    METRIC = "metric"         # 数值指标 — can be aggregated
    DIMENSION = "dimension"   # 分类维度 — used for GROUP BY
    DATE = "date"             # 时间维度 — used for time-series
    GEO = "geo"               # 地理维度 — used for maps
    ID = "id"                 # 标识符 — primary/foreign key
    TEXT = "text"             # 文本 — free text, not aggregatable
    UNKNOWN = "unknown"       # 未识别


class JoinType(str, Enum):
    """SQL join types."""
    LEFT = "LEFT JOIN"
    RIGHT = "RIGHT JOIN"
    INNER = "INNER JOIN"
    FULL = "FULL OUTER JOIN"


class AggFunction(str, Enum):
    """Default aggregation functions for metrics."""
    SUM = "SUM"
    AVG = "AVG"
    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    MIN = "MIN"
    MAX = "MAX"
    MEDIAN = "MEDIAN"
    FIRST = "FIRST"
    LAST = "LAST"


@dataclass
class ColumnDef:
    """Semantic definition of a single column.

    Attributes:
        name: Column name in the database.
        role: Semantic role (metric, dimension, date, geo, id, text).
        description: Human-readable description in Chinese.
        dtype: SQL data type.
        aliases: Alternative names/synonyms for NL matching.
        unit: Unit of measurement (元, %, 人, etc.).
        agg_default: Default aggregation for metric columns.
        is_nullable: Whether the column can be NULL.
        format: Display format hint (e.g., "currency", "percent", "date").
        tags: Free-form tags for categorization.
    """
    name: str
    role: ColumnRole = ColumnRole.UNKNOWN
    description: str = ""
    dtype: str = ""
    aliases: list[str] = field(default_factory=list)
    unit: str = ""
    agg_default: Optional[AggFunction] = None
    is_nullable: bool = True
    format: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class MetricDef:
    """Definition of a business metric (KPI).

    A metric is a named business concept that maps to a SQL expression.

    Attributes:
        name: Business name (e.g., "总销售额", "客单价").
        description: What this metric means and how it's calculated.
        sql_expr: SQL expression (e.g., "SUM(amount)", "AVG(price)").
        unit: Unit of measurement.
        format: Display format.
        depends_on: Columns this metric depends on.
        category: Grouping category (e.g., "销售", "财务", "用户").
    """
    name: str
    description: str = ""
    sql_expr: str = ""
    unit: str = ""
    format: str = ""
    depends_on: list[str] = field(default_factory=list)
    category: str = ""


@dataclass
class Relationship:
    """Join relationship between two business models.

    Attributes:
        name: Relationship name (e.g., "订单-产品关联").
        target_model: The model to join with.
        join_type: SQL join type.
        condition: ON clause (e.g., "sales.product_id = products.id").
        description: When to use this relationship.
    """
    name: str
    target_model: str
    join_type: JoinType = JoinType.LEFT
    condition: str = ""
    description: str = ""


@dataclass
class SemanticModel:
    """A complete business semantic model.

    Maps one or more database tables to business concepts, defining
    columns, metrics, and relationships.

    Attributes:
        name: Unique model name.
        table: Primary database table.
        description: Business description of what this model represents.
        columns: Column definitions with semantic metadata.
        metrics: Business metric definitions.
        relationships: JOIN relationships to other models.
        synonyms: Synonyms for the model itself (for NL matching).
        created_at: When the model was created.
        updated_at: When the model was last modified.
    """
    name: str
    table: str
    description: str = ""
    columns: list[ColumnDef] = field(default_factory=list)
    metrics: list[MetricDef] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        result = {
            "name": self.name,
            "table": self.table,
            "description": self.description,
            "synonyms": self.synonyms,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "columns": [],
            "metrics": [],
            "relationships": [],
        }
        for col in self.columns:
            d = asdict(col)
            d["role"] = col.role.value
            if col.agg_default:
                d["agg_default"] = col.agg_default.value
            result["columns"].append(d)

        for m in self.metrics:
            result["metrics"].append(asdict(m))

        for r in self.relationships:
            d = asdict(r)
            d["join_type"] = r.join_type.value
            result["relationships"].append(d)

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "SemanticModel":
        """Deserialize from dict."""
        model = cls(
            name=data["name"],
            table=data["table"],
            description=data.get("description", ""),
            synonyms=data.get("synonyms", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
        for col_data in data.get("columns", []):
            col = ColumnDef(
                name=col_data["name"],
                role=ColumnRole(col_data.get("role", "unknown")),
                description=col_data.get("description", ""),
                dtype=col_data.get("dtype", ""),
                aliases=col_data.get("aliases", []),
                unit=col_data.get("unit", ""),
                is_nullable=col_data.get("is_nullable", True),
                format=col_data.get("format", ""),
                tags=col_data.get("tags", []),
            )
            agg = col_data.get("agg_default")
            if agg:
                col.agg_default = AggFunction(agg)
            model.columns.append(col)

        for m_data in data.get("metrics", []):
            model.metrics.append(MetricDef(**m_data))

        for r_data in data.get("relationships", []):
            r_data["join_type"] = JoinType(r_data.get("join_type", "LEFT JOIN"))
            model.relationships.append(Relationship(**r_data))

        return model

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_column(self, name_or_alias: str) -> Optional[ColumnDef]:
        """Find a column by name or alias."""
        for col in self.columns:
            if col.name == name_or_alias or name_or_alias in col.aliases:
                return col
        return None

    def get_metric(self, name: str) -> Optional[MetricDef]:
        """Find a metric by name."""
        for m in self.metrics:
            if m.name == name:
                return m
        return None

    def get_metric_columns(self) -> list[ColumnDef]:
        """Get all columns with metric role."""
        return [c for c in self.columns if c.role == ColumnRole.METRIC]

    def get_dimension_columns(self) -> list[ColumnDef]:
        """Get all dimension/category columns."""
        return [c for c in self.columns if c.role == ColumnRole.DIMENSION]

    def get_date_columns(self) -> list[ColumnDef]:
        """Get all date columns."""
        return [c for c in self.columns if c.role == ColumnRole.DATE]

    def get_geo_columns(self) -> list[ColumnDef]:
        """Get all geo columns."""
        return [c for c in self.columns if c.role == ColumnRole.GEO]

    def resolve_metric_sql(self, col_or_metric: str) -> str:
        """Resolve a column name or metric name to its SQL expression.

        Args:
            col_or_metric: Either a column name or a metric name.

        Returns:
            SQL expression (e.g., "SUM(amount)" or just "amount").
        """
        # Check if it's a defined metric
        metric = self.get_metric(col_or_metric)
        if metric:
            return metric.sql_expr

        # Check if it's a column
        col = self.get_column(col_or_metric)
        if col:
            if col.agg_default and col.role == ColumnRole.METRIC:
                return f"{col.agg_default.value}({col.name})"
            return col.name

        # Fallback: just return as-is (raw column name)
        return col_or_metric

    def to_prompt_context(self) -> str:
        """Generate a compact prompt context for LLM consumption.

        This produces a text block that can be injected into the system
        prompt so the LLM understands the business semantics of the data.
        """
        lines = [f"## 业务模型: {self.name}", f"**描述**: {self.description}", ""]

        # Columns
        lines.append("### 字段")
        lines.append("| 字段 | 角色 | 描述 | 别名 | 聚合 |")
        lines.append("|------|------|------|------|------|")
        for col in self.columns:
            aliases = ", ".join(col.aliases) if col.aliases else "-"
            agg = col.agg_default.value if col.agg_default else "-"
            lines.append(
                f"| {col.name} | {col.role.value} | {col.description} | {aliases} | {agg} |"
            )

        # Metrics
        if self.metrics:
            lines.append("\n### 业务指标")
            for m in self.metrics:
                lines.append(f"- **{m.name}**: {m.description} (`{m.sql_expr}`)")

        # Relationships
        if self.relationships:
            lines.append("\n### 关联关系")
            for r in self.relationships:
                lines.append(
                    f"- **{r.name}**: {r.target_model} {r.join_type.value} ON {r.condition}"
                )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model Manager
# ---------------------------------------------------------------------------

class ModelManager:
    """Manages lifecycle of semantic models.

    Models are stored as JSON files in the semantic directory,
    making them easy to version control, share, and edit manually.

    Attributes:
        models_dir: Directory for semantic model files.
        models: In-memory cache of loaded models.
    """

    DEFAULT_DIR = "references/semantic"

    # Mapping from ColumnRole to AggFunction defaults
    ROLE_AGG_DEFAULTS = {
        ColumnRole.METRIC: AggFunction.SUM,
    }

    # Keywords that suggest a column should NOT use SUM
    RATIO_KEYWORDS = [
        "rate", "ratio", "pct", "percent", "percentage",
        "率", "比", "比例", "占比", "百分比",
        "avg", "average", "mean", "均", "平均",
        "price", "单价", "价格",
        "score", "评分", "分数",
        "index", "指数", "系数",
    ]

    def __init__(self, models_dir: str = DEFAULT_DIR):
        """Initialize the model manager.

        Args:
            models_dir: Directory for semantic model files.
        """
        self.models_dir = models_dir
        self.models: dict[str, SemanticModel] = {}
        os.makedirs(models_dir, exist_ok=True)
        self._load_all()

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    def create_from_table(
        self,
        table: str,
        db_path: str = "workspace.duckdb",
        model_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> SemanticModel:
        """Auto-create a semantic model from a database table.

        Uses the Insight Engine to profile columns and auto-detect roles,
        then generates a semantic model with sensible defaults.

        Args:
            table: Database table name.
            db_path: Path to the DuckDB database.
            model_name: Model name (defaults to table name).
            description: Model description (auto-generated if None).

        Returns:
            A SemanticModel ready to use and save.
        """
        from scripts.insight_engine import InsightEngine

        engine = InsightEngine(db_path)
        profile = engine.profile_table(table)

        if profile is None:
            raise ValueError(f"表 '{table}' 不存在或无法读取")

        model = SemanticModel(
            name=model_name or table,
            table=table,
            description=description or f"从 {table} 表自动生成的业务模型",
        )

        for col_profile in profile.columns:
            col_def = self._build_column_def(col_profile)
            model.columns.append(col_def)

        # Auto-generate metrics for metric columns
        for col in model.get_metric_columns():
            agg_default = col.agg_default or AggFunction.SUM
            metric_name = self._generate_metric_name(col, agg_default)
            model.metrics.append(MetricDef(
                name=metric_name,
                description=f"{col.description or col.name}的{agg_default.value}聚合",
                sql_expr=f"{agg_default.value}({col.name})",
                unit=col.unit,
                format=col.format,
                depends_on=[col.name],
            ))

        # Add COUNT metric
        model.metrics.append(MetricDef(
            name=f"{model.name}记录数",
            description=f"{model.description}的总记录数",
            sql_expr="COUNT(*)",
            category="基础",
        ))

        return model

    def save(self, model: SemanticModel, filename: Optional[str] = None) -> str:
        """Save a semantic model to disk.

        Args:
            model: The model to save.
            filename: Filename without extension (default: model.name).

        Returns:
            Path to the saved file.
        """
        model.updated_at = datetime.now().isoformat()
        if not model.created_at:
            model.created_at = model.updated_at

        filename = filename or model.name
        filepath = os.path.join(self.models_dir, f"{filename}.json")

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(model.to_dict(), f, ensure_ascii=False, indent=2)

        self.models[model.name] = model
        logger.info("语义模型已保存", name=model.name, path=filepath)
        return filepath

    def load(self, name: str) -> Optional[SemanticModel]:
        """Load a semantic model by name.

        Args:
            name: Model name (matches the filename without .json).

        Returns:
            SemanticModel or None if not found.
        """
        if name in self.models:
            return self.models[name]

        filepath = os.path.join(self.models_dir, f"{name}.json")
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        model = SemanticModel.from_dict(data)
        self.models[model.name] = model
        return model

    def delete(self, name: str) -> bool:
        """Delete a semantic model.

        Args:
            name: Model name to delete.

        Returns:
            True if deleted, False if not found.
        """
        filepath = os.path.join(self.models_dir, f"{name}.json")
        if os.path.exists(filepath):
            os.unlink(filepath)
            self.models.pop(name, None)
            logger.info("语义模型已删除", name=name)
            return True
        return False

    def list_models(self) -> list[dict]:
        """List all available semantic models.

        Returns:
            List of {name, table, description, columns, metrics} dicts.
        """
        result = []
        for name, model in self.models.items():
            result.append({
                "name": model.name,
                "table": model.table,
                "description": model.description,
                "columns": len(model.columns),
                "metrics": len(model.metrics),
                "relationships": len(model.relationships),
            })
        return sorted(result, key=lambda m: m["name"])

    def get_prompt_context(self, model_names: Optional[list[str]] = None) -> str:
        """Get combined prompt context for one or more models.

        Args:
            model_names: List of model names (all loaded models if None).

        Returns:
            Text block suitable for LLM context injection.
        """
        if model_names is None:
            models = list(self.models.values())
        else:
            models = [self.load(n) for n in model_names]
            models = [m for m in models if m is not None]

        if not models:
            return ""

        sections = []
        for model in models:
            sections.append(model.to_prompt_context())

        return "\n\n---\n\n".join(sections)

    # ------------------------------------------------------------------
    # Column helpers
    # ------------------------------------------------------------------

    def _build_column_def(self, col_profile) -> ColumnDef:
        """Build a ColumnDef from an Insight Engine ColumnProfile.

        Auto-infers the semantic role, default aggregation, and
        generates Chinese descriptions.
        """
        # Determine role
        if col_profile.is_date:
            role = ColumnRole.DATE
        elif col_profile.is_id:
            role = ColumnRole.ID
        elif col_profile.is_geo:
            role = ColumnRole.GEO
        elif col_profile.is_metric:
            role = ColumnRole.METRIC
        elif col_profile.is_category:
            role = ColumnRole.DIMENSION
        else:
            role = ColumnRole.TEXT

        # Generate description
        description = self._generate_description(col_profile, role)

        # Determine default aggregation
        agg_default = None
        if role == ColumnRole.METRIC:
            if self._is_ratio_metric(col_profile.name):
                agg_default = AggFunction.AVG
            else:
                agg_default = AggFunction.SUM

        # Determine format
        fmt = ""
        if role == ColumnRole.DATE:
            fmt = "date"
        elif role == ColumnRole.METRIC:
            if self._is_ratio_metric(col_profile.name):
                fmt = "percent"
            elif "金额" in col_profile.name or "价格" in col_profile.name or "price" in col_profile.name.lower():
                fmt = "currency"

        # Determine unit
        unit = ""
        if "金额" in col_profile.name or "价格" in col_profile.name:
            unit = "元"
        elif "数量" in col_profile.name or "quantity" in col_profile.name.lower():
            unit = "件"
        elif "率" in col_profile.name or "rate" in col_profile.name.lower():
            unit = "%"

        # Generate aliases
        aliases = self._generate_aliases(col_profile.name, role)

        return ColumnDef(
            name=col_profile.name,
            role=role,
            description=description,
            dtype=col_profile.dtype,
            aliases=aliases,
            unit=unit,
            agg_default=agg_default,
            is_nullable=col_profile.null_pct > 0,
            format=fmt,
        )

    def _generate_description(self, col_profile, role: ColumnRole) -> str:
        """Generate a human-readable description for a column."""
        name = col_profile.name

        # Try to create a meaningful description
        desc_parts = []

        if role == ColumnRole.METRIC:
            desc_parts.append(f"数值指标")
            if col_profile.mean is not None:
                desc_parts.append(f"均值{col_profile.mean:.1f}")
        elif role == ColumnRole.DIMENSION:
            desc_parts.append(f"分类维度，{col_profile.unique_count}个不同值")
        elif role == ColumnRole.DATE:
            desc_parts.append("时间维度")
            if col_profile.date_range_days:
                desc_parts.append(f"跨度{col_profile.date_range_days}天")
        elif role == ColumnRole.GEO:
            desc_parts.append("地理维度")
        elif role == ColumnRole.ID:
            desc_parts.append("唯一标识符")
        else:
            desc_parts.append("文本字段")

        return "，".join(desc_parts) if desc_parts else name

    def _generate_aliases(self, name: str, role: ColumnRole) -> list[str]:
        """Generate common aliases/synonyms for a column name."""
        aliases = []

        # Common Chinese ↔ English mappings
        mapping = {
            "金额": ["销售额", "收入", "营收", "revenue", "sales"],
            "数量": ["销量", "件数", "quantity", "count"],
            "单价": ["价格", "均价", "price", "unit_price"],
            "日期": ["时间", "date", "time"],
            "省份": ["省", "province", "region"],
            "城市": ["市", "city"],
            "渠道": ["来源", "channel", "source"],
            "分类": ["类别", "类型", "category", "type"],
            "会员": ["用户", "member", "user"],
            "订单": ["order", "订单号"],
            "商品": ["产品", "product", "item"],
            "客户": ["顾客", "customer", "client"],
        }

        for keyword, synonyms in mapping.items():
            if keyword in name or keyword.lower() in name.lower():
                aliases.extend(synonyms)

        return list(set(aliases))

    def _generate_metric_name(self, col: ColumnDef, agg: AggFunction) -> str:
        """Generate a natural metric name from column + aggregation."""
        agg_labels = {
            AggFunction.SUM: "总",
            AggFunction.AVG: "平均",
            AggFunction.COUNT: "",
            AggFunction.COUNT_DISTINCT: "去重",
            AggFunction.MAX: "最高",
            AggFunction.MIN: "最低",
        }
        prefix = agg_labels.get(agg, "")
        desc = col.description or col.name
        # Pick the shortest reasonable name
        if col.aliases:
            return f"{prefix}{col.aliases[0]}"
        return f"{prefix}{col.name}"

    def _is_ratio_metric(self, name: str) -> bool:
        """Check if a column name suggests it's a ratio/rate metric."""
        lower = name.lower()
        return any(kw in lower for kw in self.RATIO_KEYWORDS)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """Load all semantic models from disk."""
        if not os.path.isdir(self.models_dir):
            return

        for filename in sorted(os.listdir(self.models_dir)):
            if filename.endswith(".json"):
                name = filename[:-5]  # remove .json
                try:
                    self.load(name)
                except Exception as e:
                    logger.warning("语义模型加载失败", filename=filename, error=str(e))


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def main():
    """Command-line interface for semantic model management."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Semantic Model Manager — Business-aware data modeling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-create model from table
  python scripts/semantic_model.py create orders --db workspace.duckdb

  # List all models
  python scripts/semantic_model.py list

  # Show a model's details
  python scripts/semantic_model.py show orders

  # Generate prompt context for LLM
  python scripts/semantic_model.py context orders

  # Delete a model
  python scripts/semantic_model.py delete orders
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # create command
    create_parser = subparsers.add_parser("create", help="Create semantic model from table")
    create_parser.add_argument("table", help="Table name")
    create_parser.add_argument("--name", "-n", help="Model name (default: table name)")
    create_parser.add_argument("--desc", "-d", help="Model description")
    create_parser.add_argument("--db", default="workspace.duckdb", help="Database path")
    create_parser.add_argument("--format", choices=["json", "text"], default="text")

    # list command
    list_parser = subparsers.add_parser("list", help="List all models")

    # show command
    show_parser = subparsers.add_parser("show", help="Show model details")
    show_parser.add_argument("name", help="Model name")
    show_parser.add_argument("--format", choices=["json", "text"], default="text")

    # context command
    context_parser = subparsers.add_parser("context", help="Generate LLM prompt context")
    context_parser.add_argument("names", nargs="*", help="Model names (all if empty)")

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a model")
    delete_parser.add_argument("name", help="Model name")

    args = parser.parse_args()
    mgr = ModelManager()

    if args.command == "create":
        try:
            model = mgr.create_from_table(
                args.table,
                db_path=args.db,
                model_name=args.name,
                description=args.desc,
            )
            path = mgr.save(model, args.name or args.table)
            if args.format == "json":
                print(json.dumps(model.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(f"✅ 语义模型已创建: {model.name}")
                print(f"   表: {model.table}")
                print(f"   字段: {len(model.columns)} 个")
                print(f"   指标: {len(model.metrics)} 个")
                print(f"   路径: {path}")
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)

    elif args.command == "list":
        models = mgr.list_models()
        if not models:
            print("📭 暂无语义模型。使用 'create' 命令创建。")
            return
        print(f"📊 共 {len(models)} 个语义模型:\n")
        print(f"{'名称':<20} {'表':<20} {'字段':<6} {'指标':<6} {'描述'}")
        print("-" * 80)
        for m in models:
            print(f"{m['name']:<20} {m['table']:<20} {m['columns']:<6} {m['metrics']:<6} {m['description'][:30]}")

    elif args.command == "show":
        model = mgr.load(args.name)
        if model is None:
            print(f"❌ 模型 '{args.name}' 不存在")
            sys.exit(1)
        if args.format == "json":
            print(json.dumps(model.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(model.to_prompt_context())

    elif args.command == "context":
        ctx = mgr.get_prompt_context(args.names if args.names else None)
        print(ctx if ctx else "暂无模型上下文。")

    elif args.command == "delete":
        if mgr.delete(args.name):
            print(f"✅ 语义模型 '{args.name}' 已删除")
        else:
            print(f"❌ 模型 '{args.name}' 不存在")
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
