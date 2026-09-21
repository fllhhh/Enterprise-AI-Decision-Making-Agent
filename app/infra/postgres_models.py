"""PostgreSQL ORM 模型。

模型映射 AI 查询使用的只读视图，而不是直接映射原始业务表。DDL 由
``database/postgres`` 下的 SQL 脚本执行，应用启动时不会调用
``Base.metadata.create_all()``。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 PostgreSQL ORM 模型的声明式基类。"""


class AiSalesOrder(Base):
    """映射 ``v_ai_sales_orders`` 只读销售视图。"""

    __tablename__ = "v_ai_sales_orders"
    __table_args__ = {"info": {"read_only": True}}

    order_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class AiInventorySnapshot(Base):
    """映射 ``v_ai_inventory_snapshots`` 只读库存视图。"""

    __tablename__ = "v_ai_inventory_snapshots"
    __table_args__ = {"info": {"read_only": True}}

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    department_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    warehouse_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_in_transit: Mapped[int] = mapped_column(Integer, nullable=False)

