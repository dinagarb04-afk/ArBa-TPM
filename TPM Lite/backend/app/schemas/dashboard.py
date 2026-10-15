from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

type IntegrationState = Literal["successful", "attention_required", "unknown"]
type PromotionState = Literal[
    "pending_approval", "draft", "approved", "action_required"
]
type DashboardNumber = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
]


class DashboardKpis(BaseModel):
    pending_my_approval: int
    action_required: int
    upcoming_promotions: int
    planned_promo_spend: DashboardNumber
    currency: str
    upcoming_period_weeks: int


class PendingPromotion(BaseModel):
    id: str
    promotion_id: str
    name: str
    plan_account: str
    start_date: date
    end_date: date
    planned_spend: DashboardNumber
    planned_contribution: DashboardNumber
    currency: str
    submitted_at: datetime
    status: PromotionState
    tactic: str
    market: str
    brand: str
    starting_soon: bool
    negative_contribution: bool
    validation_warnings: bool


class AttentionItem(BaseModel):
    promotion_id: str
    name: str
    plan_account: str
    reason: str
    severity: Literal["warning", "critical"]
    status: PromotionState


class WeeklyPlanningPoint(BaseModel):
    week: str
    baseline_volume: DashboardNumber
    promo_uplift: DashboardNumber


class PlanningSnapshot(BaseModel):
    baseline_volume: DashboardNumber
    promo_uplift: DashboardNumber
    total_forecast: DashboardNumber
    uom: str
    weekly_data: list[WeeklyPlanningPoint]


class PromotionFinancials(BaseModel):
    gross_sales_value: DashboardNumber
    planned_promo_spend: DashboardNumber
    net_sales_value: DashboardNumber
    planned_contribution: DashboardNumber
    negative_contribution_count: int
    currency: str


class IntegrationHealth(BaseModel):
    status: IntegrationState
    summary: str
    last_event: datetime | None = None


class IntegrationStatuses(BaseModel):
    sap_master_data: IntegrationHealth
    sap_promotions: IntegrationHealth
    p10_arete: IntegrationHealth


class RoleConfiguration(BaseModel):
    source: Literal["not_configured"] = "not_configured"
    available_roles: list[str] = Field(default_factory=list)
    preferred_widget_order: list[str] = Field(default_factory=list)


class PromotionItemDetail(BaseModel):
    osku: str
    description: str
    uom: str
    baseline_volume: DashboardNumber
    planned_volume: DashboardNumber
    regular_price: DashboardNumber
    spend_type: str
    spend_amount: DashboardNumber
    spend_treatment: str
    landed_price: DashboardNumber
    planned_spend: DashboardNumber
    planned_contribution: DashboardNumber
    validation_messages: list[str]


class PromotionDetail(PendingPromotion):
    description: str
    gross_sales_value: DashboardNumber
    net_sales_value: DashboardNumber
    validation_messages: list[str]
    items: list[PromotionItemDetail]


class DashboardOverview(BaseModel):
    data_source: Literal["synthetic_development"] = "synthetic_development"
    generated_at: datetime
    disclaimer: str
    kpis: DashboardKpis
    pending_approvals: list[PendingPromotion]
    attention_items: list[AttentionItem]
    upcoming_items: list[PendingPromotion]
    planning_snapshot: PlanningSnapshot
    promotion_financials: PromotionFinancials
    integration_status: IntegrationStatuses
    role_configuration: RoleConfiguration
