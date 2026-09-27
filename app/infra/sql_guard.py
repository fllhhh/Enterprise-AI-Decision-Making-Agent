"""使用 SQLGlot 对受控 SQL 执行 AST 级安全校验。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.domain.errors import UnsafeSqlError
from app.infra.schema_catalog import SchemaCatalog


@dataclass(frozen=True, slots=True)
class SqlPolicy:
    """单次 SQL 校验允许访问的表和最大返回行数。"""

    allowed_views: frozenset[str]
    allowed_columns: dict[str, frozenset[str]]
    max_rows: int

    @classmethod
    def from_catalog(
        cls,
        catalog: SchemaCatalog,
        *,
        max_rows: int,
    ) -> "SqlPolicy":
        """从 Schema Catalog 创建全局白名单策略。"""
        views = catalog.allowed_views()
        return cls(
            allowed_views=views,
            allowed_columns={
                view: catalog.allowed_columns(view)
                for view in views
            },
            max_rows=max_rows,
        )


class SqlGuard:
    """只接受通过 AST 白名单校验的只读 SELECT。"""

    def validate(self, sql: str, *, policy: SqlPolicy) -> str:
        """解析并校验 SQL，返回标准化 SQL 文本。"""
        normalized = sql.strip()
        if not normalized:
            raise UnsafeSqlError("SQL 不能为空")

        try:
            statements = parse(normalized, read="postgres")
        except ParseError as exc:
            raise UnsafeSqlError("SQL 语法无法解析") from exc
        if len(statements) != 1:
            raise UnsafeSqlError("只允许执行一条 SQL 语句")

        expression = statements[0]
        if not isinstance(expression, exp.Select):
            raise UnsafeSqlError("只允许执行 SELECT 查询")
        if expression.args.get("with"):
            raise UnsafeSqlError("受控查询不允许使用 CTE")
        if any(True for _ in expression.find_all(exp.Subquery)):
            raise UnsafeSqlError("受控查询不允许使用子查询")
        if any(True for _ in expression.find_all(exp.Star)):
            raise UnsafeSqlError("受控查询不允许使用 SELECT *")

        self._validate_tables(expression, policy)
        self._validate_columns(expression, policy)
        self._validate_limit(expression, policy)
        return expression.sql(dialect="postgres")

    def _validate_tables(self, expression: exp.Expression, policy: SqlPolicy) -> None:
        """拒绝 Catalog 之外的视图和任何写操作目标。"""
        tables = list(expression.find_all(exp.Table))
        if not tables:
            raise UnsafeSqlError("SELECT 必须指定 Catalog 中的只读视图")
        for table in tables:
            if table.name not in policy.allowed_views:
                raise UnsafeSqlError(f"不允许访问数据表: {table.name}")

    def _validate_columns(self, expression: exp.Expression, policy: SqlPolicy) -> None:
        """校验查询引用的列均在白名单内。

        SELECT 输出别名（如 ``SUM(amount) AS total_amount`` 后的
        ``ORDER BY total_amount``）由服务端模板生成，不属于对底层
        列的访问，因此允许出现在 ORDER BY / GROUP BY 中。
        """
        output_aliases = {alias.alias for alias in expression.find_all(exp.Alias)}
        for column in expression.find_all(exp.Column):
            if not column.name:
                continue
            table = column.table or ""
            if table:
                allowed = policy.allowed_columns.get(table, frozenset())
                if column.name not in allowed:
                    raise UnsafeSqlError(f"不允许访问列: {table}.{column.name}")
                continue

            if column.name in output_aliases:
                continue
            allowed = frozenset().union(*policy.allowed_columns.values())
            if column.name not in allowed:
                raise UnsafeSqlError(f"不允许访问列: {column.name}")

    def _validate_limit(self, expression: exp.Expression, policy: SqlPolicy) -> None:
        """要求有且只有一个不超上限的 LIMIT。"""
        limits = list(expression.find_all(exp.Limit))
        if len(limits) != 1:
            raise UnsafeSqlError("受控查询必须且只能包含一个 LIMIT")
        limit = limits[0].expression
        if not isinstance(limit, exp.Literal) or not limit.is_int:
            raise UnsafeSqlError("LIMIT 必须是固定整数")
        if int(limit.name) > policy.max_rows:
            raise UnsafeSqlError(f"LIMIT 不能超过 {policy.max_rows}")
