"""使用 SQLAlchemy ORM 表达式构建白名单查询。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, func, literal, select, true
from sqlalchemy.sql.elements import ColumnElement

from app.infra.postgres_models import AiInventorySnapshot, AiSalesOrder


def build_sales_summary(parameters: Mapping[str, Any]) -> Select[Any]:
    """按月份汇总权限范围内的销售额和订单量。"""
    period = func.to_char(
        AiSalesOrder.order_date,
        literal("YYYY-MM"),
    ).label("period")
    statement = (
        select(
            period,
            func.sum(AiSalesOrder.amount).label("total_amount"),
            func.count(AiSalesOrder.order_id).label("order_count"),
        )
        .where(
            _permission_clause(AiSalesOrder, parameters),
            AiSalesOrder.order_date.between(
                parameters["period_start"],
                parameters["period_end"],
            ),
        )
        .group_by(period)
        .order_by(period)
        .limit(_positive_int(parameters, "row_limit"))
    )
    return statement


def build_top_products(parameters: Mapping[str, Any]) -> Select[Any]:
    """按销售额降序查询权限范围内的畅销商品。"""
    statement = (
        select(
            AiSalesOrder.product_id,
            func.sum(AiSalesOrder.quantity).label("total_quantity"),
            func.sum(AiSalesOrder.amount).label("total_amount"),
        )
        .where(
            _permission_clause(AiSalesOrder, parameters),
            AiSalesOrder.order_date.between(
                parameters["period_start"],
                parameters["period_end"],
            ),
        )
        .group_by(AiSalesOrder.product_id)
        .order_by(func.sum(AiSalesOrder.amount).desc())
        .limit(_positive_int(parameters, "top_n"))
    )
    return statement


def build_inventory_balance(parameters: Mapping[str, Any]) -> Select[Any]:
    """按商品汇总权限范围内的在库和在途数量。"""
    statement = (
        select(
            AiInventorySnapshot.product_id,
            func.sum(AiInventorySnapshot.quantity_on_hand).label("quantity_on_hand"),
            func.sum(AiInventorySnapshot.quantity_in_transit).label(
                "quantity_in_transit"
            ),
        )
        .where(_permission_clause(AiInventorySnapshot, parameters))
        .group_by(AiInventorySnapshot.product_id)
        .order_by(func.sum(AiInventorySnapshot.quantity_on_hand).desc())
        .limit(_positive_int(parameters, "row_limit"))
    )
    return statement


def _permission_clause(
    model: type[AiSalesOrder] | type[AiInventorySnapshot],
    parameters: Mapping[str, Any],
) -> ColumnElement[bool]:
    """根据可信 Principal 生成的参数构建部门范围条件。"""
    if int(parameters.get("include_all_departments", 0)) == 1:
        return true()
    return model.department_id == str(parameters["department_id"])


def _positive_int(parameters: Mapping[str, Any], name: str) -> int:
    """读取并校验查询上限，避免无效的 LIMIT。"""
    value = int(parameters.get(name, 200))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value

