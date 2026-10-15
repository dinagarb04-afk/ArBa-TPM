from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Market(Base):
    __tablename__ = "market"
    __table_args__ = (
        CheckConstraint("plan_mode IN ('VOL', 'PROMO')", name="ck_market_plan_mode"),
        CheckConstraint("horizon_weeks > 0", name="ck_market_horizon_positive"),
    )

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    p10_sales_org: Mapped[str] = mapped_column(String(12), nullable=False)
    horizon_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=52)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CustomerL04(Base):
    __tablename__ = "customer_l04"
    __table_args__ = (
        UniqueConstraint("market_code", "name", name="uq_customer_market_name"),
        UniqueConstraint("market_code", "id", name="uq_customer_market_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_l03: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductHierarchy(Base):
    __tablename__ = "product_hierarchy"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 9", name="ck_hierarchy_level"),
        ForeignKeyConstraint(["parent_id"], ["product_hierarchy.node_id"]),
    )

    node_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String(80))
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(200), nullable=False)


class ProductP09(Base):
    __tablename__ = "product_p09"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    brand: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sub_brand: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    hierarchy_node_id: Mapped[str] = mapped_column(
        ForeignKey("product_hierarchy.node_id"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MaterialP10(Base):
    __tablename__ = "material_p10"

    material: Mapped[str] = mapped_column(String(40), primary_key=True)
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    p09_code: Mapped[str] = mapped_column(
        ForeignKey("product_p09.code"), nullable=False, index=True
    )
    case_uom: Mapped[str] = mapped_column(String(10), nullable=False, default="CS")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class P09P10Split(Base):
    __tablename__ = "p09_p10_split"
    __table_args__ = (
        CheckConstraint("share >= 0 AND share <= 100", name="ck_split_share_range"),
        CheckConstraint("source IN ('CALC', 'MANUAL')", name="ck_split_source"),
    )

    p09_code: Mapped[str] = mapped_column(ForeignKey("product_p09.code"), primary_key=True)
    material: Mapped[str] = mapped_column(ForeignKey("material_p10.material"), primary_key=True)
    valid_from: Mapped[date] = mapped_column(Date, primary_key=True)
    share: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)


class Tactic(Base):
    __tablename__ = "tactic"

    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint("role IN ('PLANNER', 'APPROVER', 'ADMIN', 'VIEWER')", name="ck_user_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UserAssignment(Base):
    __tablename__ = "user_assignment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["market_code", "customer_id"],
            ["customer_l04.market_code", "customer_l04.id"],
            name="fk_assignment_market_customer",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer_l04.id"), primary_key=True)


class Listing(Base):
    __tablename__ = "listing"
    __table_args__ = (
        ForeignKeyConstraint(
            ["market_code", "customer_id"],
            ["customer_l04.market_code", "customer_l04.id"],
            name="fk_listing_market_customer",
        ),
    )

    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer_l04.id"), primary_key=True)
    p09_code: Mapped[str] = mapped_column(ForeignKey("product_p09.code"), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Baseline(Base):
    __tablename__ = "baseline"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL', 'UPLOAD')", name="ck_baseline_source"),
        CheckConstraint("qty_cs >= 0", name="ck_baseline_nonnegative"),
        ForeignKeyConstraint(
            ["market_code", "customer_id"],
            ["customer_l04.market_code", "customer_l04.id"],
            name="fk_baseline_market_customer",
        ),
        Index("ix_baseline_market_customer_week", "market_code", "customer_id", "iso_week"),
    )

    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer_l04.id"), primary_key=True)
    p09_code: Mapped[str] = mapped_column(ForeignKey("product_p09.code"), primary_key=True)
    iso_week: Mapped[str] = mapped_column(String(8), primary_key=True)
    qty_cs: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(320), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ActualSellIn(Base):
    __tablename__ = "actual_sellin"
    __table_args__ = (
        CheckConstraint("qty_cs >= 0", name="ck_actual_nonnegative"),
        ForeignKeyConstraint(
            ["market_code", "customer_id"],
            ["customer_l04.market_code", "customer_l04.id"],
            name="fk_actual_market_customer",
        ),
        Index("ix_actual_market_customer_week", "market_code", "customer_id", "iso_week"),
    )

    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer_l04.id"), primary_key=True)
    p09_code: Mapped[str] = mapped_column(ForeignKey("product_p09.code"), primary_key=True)
    iso_week: Mapped[str] = mapped_column(String(8), primary_key=True)
    qty_cs: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Promotion(Base):
    __tablename__ = "promotion"
    __table_args__ = (
        CheckConstraint(
            "status IN ('NEW', 'SAVED', 'CHANGED', 'APPROVED')",
            name="ck_promotion_status",
        ),
        CheckConstraint("version > 0", name="ck_promotion_version"),
        CheckConstraint("end_date >= start_date", name="ck_promotion_date_range"),
        CheckConstraint("cons_end >= cons_start", name="ck_promotion_consumption_range"),
        ForeignKeyConstraint(
            ["market_code", "customer_id"],
            ["customer_l04.market_code", "customer_l04.id"],
            name="fk_promotion_market_customer",
        ),
        ForeignKeyConstraint(
            ["market_code", "tactic"],
            ["tactic.market_code", "tactic.name"],
            name="fk_promotion_market_tactic",
        ),
        Index(
            "ix_promotion_market_customer_dates",
            "market_code",
            "customer_id",
            "start_date",
            "end_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer_l04.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    cons_start: Mapped[date] = mapped_column(Date, nullable=False)
    cons_end: Mapped[date] = mapped_column(Date, nullable=False)
    tactic: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="NEW")
    created_by: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    approved_by: Mapped[str | None] = mapped_column(String(320))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PromotionItem(Base):
    __tablename__ = "promotion_item"
    __table_args__ = (CheckConstraint("total_cs >= 0", name="ck_promotion_item_total_nonnegative"),)

    promotion_id: Mapped[int] = mapped_column(
        ForeignKey("promotion.id", ondelete="CASCADE"), primary_key=True
    )
    p09_code: Mapped[str] = mapped_column(ForeignKey("product_p09.code"), primary_key=True)
    total_cs: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)


class PromotionStatusLog(Base):
    __tablename__ = "promotion_status_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(
        ForeignKey("promotion.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    user: Mapped[str] = mapped_column(String(320), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(10))
    new_status: Mapped[str] = mapped_column(String(10), nullable=False)


class Pipeline(Base):
    __tablename__ = "pipeline"
    __table_args__ = (
        CheckConstraint("direction IN ('INBOUND', 'OUTBOUND')", name="ck_pipeline_direction"),
    )

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(100), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class PipelineRun(Base):
    __tablename__ = "pipeline_run"
    __table_args__ = (
        CheckConstraint("trigger IN ('MANUAL', 'SCHEDULE')", name="ck_run_trigger"),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL')",
            name="ck_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipeline.id"), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="QUEUED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    file_ref: Mapped[str | None] = mapped_column(String(500))


class PipelineRunError(Base):
    __tablename__ = "pipeline_run_error"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str] = mapped_column(Text, nullable=False)


class P10Outbound(Base):
    __tablename__ = "p10_outbound"
    __table_args__ = (
        CheckConstraint(
            "base >= 0 AND lift >= 0 AND total >= 0 AND total = base + lift",
            name="ck_outbound_volumes",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_run.id"), nullable=False, index=True)
    market_code: Mapped[str] = mapped_column(ForeignKey("market.code"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    plan_account: Mapped[str] = mapped_column(String(200), nullable=False)
    material: Mapped[str] = mapped_column(String(40), nullable=False)
    base: Mapped[int] = mapped_column(Integer, nullable=False)
    lift: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    promo_number: Mapped[str] = mapped_column(String(100), nullable=False)
    cons_start: Mapped[date] = mapped_column(Date, nullable=False)
    cons_end: Mapped[date] = mapped_column(Date, nullable=False)
    sales_org: Mapped[str] = mapped_column(String(12), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity_ts", "entity", "entity_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    user: Mapped[str] = mapped_column(String(320), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    before_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
