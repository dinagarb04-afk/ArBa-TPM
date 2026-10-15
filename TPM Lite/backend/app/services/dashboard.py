from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from app.core.config import get_settings
from app.schemas.dashboard import (
    AttentionItem,
    DashboardKpis,
    DashboardOverview,
    IntegrationHealth,
    IntegrationStatuses,
    PendingPromotion,
    PlanningSnapshot,
    PromotionDetail,
    PromotionFinancials,
    PromotionItemDetail,
    RoleConfiguration,
    WeeklyPlanningPoint,
)

DEMO_DISCLAIMER = (
    "Synthetic development data only. No customer, company, SAP, or P10 records "
    "are connected. Financial and volume measures are illustrative planning estimates."
)


class DashboardDataService:
    """Provides clearly synthetic dashboard fixtures until domain services exist."""

    def __init__(self) -> None:
        self._today = date.today()
        self._now = datetime.now(UTC)
        self._upcoming_period_weeks = get_settings().dashboard_upcoming_period_weeks
        self._promotions = self._build_promotions()

    def overview(self) -> DashboardOverview:
        pending = [
            item for item in self._promotions if item.status == "pending_approval"
        ]
        upcoming = sorted(
            (
                item
                for item in self._promotions
                if self._today
                <= item.start_date
                <= self._today + timedelta(weeks=self._upcoming_period_weeks)
            ),
            key=lambda item: item.start_date,
        )
        planning = self._planning_snapshot()
        return DashboardOverview(
            generated_at=self._now,
            disclaimer=DEMO_DISCLAIMER,
            kpis=DashboardKpis(
                pending_my_approval=6,
                action_required=4,
                upcoming_promotions=12,
                planned_promo_spend=Decimal("1240000"),
                currency="USD",
                upcoming_period_weeks=self._upcoming_period_weeks,
            ),
            pending_approvals=pending[:5],
            attention_items=self._attention_items(),
            upcoming_items=upcoming[:6],
            planning_snapshot=planning,
            promotion_financials=PromotionFinancials(
                gross_sales_value=Decimal("5800000"),
                planned_promo_spend=Decimal("1240000"),
                net_sales_value=Decimal("4560000"),
                planned_contribution=Decimal("1310000"),
                negative_contribution_count=2,
                currency="USD",
            ),
            integration_status=IntegrationStatuses(
                sap_master_data=IntegrationHealth(
                    status="successful",
                    summary="Last synchronization successful",
                    last_event=self._now - timedelta(hours=3),
                ),
                sap_promotions=IntegrationHealth(
                    status="attention_required",
                    summary="2 promotions failed",
                    last_event=self._now - timedelta(minutes=35),
                ),
                p10_arete=IntegrationHealth(
                    status="successful",
                    summary="Forecast transmission successful",
                    last_event=self._now - timedelta(hours=1),
                ),
            ),
            role_configuration=RoleConfiguration(),
        )

    def promotion_detail(self, promotion_id: str) -> PromotionDetail | None:
        promotion = next(
            (item for item in self._promotions if item.id == promotion_id), None
        )
        if promotion is None:
            return None
        item = PromotionItemDetail(
            osku="OSKU-104",
            description="Synthetic household essentials case",
            uom="CS",
            baseline_volume=Decimal("12000"),
            planned_volume=Decimal("15000"),
            regular_price=Decimal("10.00"),
            spend_type="Per-unit rate",
            spend_amount=Decimal("1.25"),
            spend_treatment="On-invoice",
            landed_price=Decimal("8.75"),
            planned_spend=Decimal("18750"),
            planned_contribution=promotion.planned_contribution,
            validation_messages=(
                ["Review unit cost basis before approval."]
                if promotion.validation_warnings
                else []
            ),
        )
        return PromotionDetail(
            **promotion.model_dump(),
            description=(
                "Synthetic development promotion for dashboard and review navigation."
            ),
            gross_sales_value=Decimal("150000"),
            net_sales_value=Decimal("131250"),
            validation_messages=item.validation_messages,
            items=[item],
        )

    def worklist(self, filter_name: str) -> list[PendingPromotion]:
        overview = self.overview()
        if filter_name == "pending-approval":
            return overview.pending_approvals
        if filter_name == "action-required":
            promotion_ids = {item.promotion_id for item in overview.attention_items}
            return [item for item in self._promotions if item.id in promotion_ids]
        if filter_name == "upcoming":
            return overview.upcoming_items
        if filter_name == "negative-contribution":
            return [item for item in self._promotions if item.negative_contribution]
        if filter_name == "planned-spend":
            return self._promotions
        return self._promotions

    def _build_promotions(self) -> list[PendingPromotion]:
        examples = [
            (
                "PROMO-1045",
                "Summer Price Drop",
                "Tesco",
                2,
                15,
                "125000",
                "48000",
                2,
                False,
                False,
                "Price Reduction",
                "UK",
                "Home Care",
            ),
            (
                "PROMO-1046",
                "Spring Home Reset",
                "Northstar Market",
                8,
                21,
                "275000",
                "-12000",
                4,
                True,
                True,
                "Feature & Display",
                "US",
                "Household",
            ),
            (
                "PROMO-1047",
                "Pure Living Value Event",
                "Harbor & Pine Retail",
                20,
                27,
                "84000",
                "32000",
                1,
                False,
                False,
                "Multi-buy",
                "US",
                "Personal Care",
            ),
            (
                "PROMO-1048",
                "Fresh Start Bundle",
                "Tesco",
                1,
                8,
                "196000",
                "76000",
                3,
                False,
                True,
                "Bundle",
                "UK",
                "Home Care",
            ),
            (
                "PROMO-1049",
                "Everyday Essentials Feature",
                "Northstar Market",
                5,
                12,
                "118000",
                "41000",
                5,
                False,
                False,
                "Feature",
                "US",
                "Household",
            ),
            (
                "PROMO-1050",
                "Weekend Value Offer",
                "Tesco",
                35,
                42,
                "92000",
                "28000",
                1,
                False,
                False,
                "Price Reduction",
                "UK",
                "Home Care",
            ),
            (
                "PROMO-1051",
                "Autumn Pantry Event",
                "Harbor & Pine Retail",
                12,
                19,
                "73000",
                "-6000",
                2,
                True,
                False,
                "Multi-buy",
                "US",
                "Food Storage",
            ),
            (
                "PROMO-1052",
                "Home Essentials Refresh",
                "Harbor & Pine Retail",
                10,
                17,
                "65000",
                "18000",
                1,
                False,
                True,
                "Feature",
                "US",
                "Household",
            ),
            (
                "PROMO-1053",
                "Spring Savings Feature",
                "Tesco",
                14,
                21,
                "78000",
                "22000",
                1,
                False,
                False,
                "Price Reduction",
                "UK",
                "Home Care",
            ),
        ]
        results: list[PendingPromotion] = []
        for (
            code,
            name,
            account,
            start_offset,
            duration,
            spend,
            contribution,
            submitted_days,
            negative,
            warnings,
            tactic,
            market,
            brand,
        ) in examples:
            start = self._today + timedelta(days=start_offset)
            results.append(
                PendingPromotion(
                    id=code.lower(),
                    promotion_id=code,
                    name=name,
                    plan_account=account,
                    start_date=start,
                    end_date=start + timedelta(days=duration),
                    planned_spend=Decimal(spend),
                    planned_contribution=Decimal(contribution),
                    currency="USD",
                    submitted_at=datetime.combine(
                        self._today - timedelta(days=submitted_days),
                        time(hour=10),
                        tzinfo=UTC,
                    ),
                    status=(
                        "approved"
                        if code == "PROMO-1050"
                        else "action_required"
                        if code in {"PROMO-1052", "PROMO-1053"}
                        else "pending_approval"
                    ),
                    tactic=tactic,
                    market=market,
                    brand=brand,
                    starting_soon=start_offset <= 7,
                    negative_contribution=negative,
                    validation_warnings=warnings,
                )
            )
        return results

    def _attention_items(self) -> list[AttentionItem]:
        return [
            AttentionItem(
                promotion_id="promo-1046",
                name="Spring Home Reset",
                plan_account="Northstar Market",
                reason="Planned contribution is negative; review economics.",
                severity="critical",
                status="action_required",
            ),
            AttentionItem(
                promotion_id="promo-1048",
                name="Fresh Start Bundle",
                plan_account="Tesco",
                reason="Validation warning: review unit cost basis.",
                severity="warning",
                status="action_required",
            ),
            AttentionItem(
                promotion_id="promo-1052",
                name="Home Essentials Refresh",
                plan_account="Harbor & Pine Retail",
                reason="Required promotion dates are incomplete.",
                severity="warning",
                status="draft",
            ),
            AttentionItem(
                promotion_id="promo-1053",
                name="Spring Savings Feature",
                plan_account="Tesco",
                reason="Promotion interface transmission needs attention.",
                severity="critical",
                status="action_required",
            ),
        ]

    def _planning_snapshot(self) -> PlanningSnapshot:
        weeks = [
            (self._today + timedelta(weeks=index)).isocalendar().week
            for index in range(1, 7)
        ]
        baseline = [
            Decimal(v) for v in ("65000", "68000", "70000", "72000", "74000", "71000")
        ]
        uplift = [
            Decimal(v) for v in ("10000", "11000", "12000", "13000", "14000", "12000")
        ]
        baseline_total = sum(baseline, Decimal(0))
        uplift_total = sum(uplift, Decimal(0))
        return PlanningSnapshot(
            baseline_volume=baseline_total,
            promo_uplift=uplift_total,
            total_forecast=baseline_total + uplift_total,
            uom="CS",
            weekly_data=[
                WeeklyPlanningPoint(
                    week=f"W{week:02d}",
                    baseline_volume=baseline[index],
                    promo_uplift=uplift[index],
                )
                for index, week in enumerate(weeks)
            ],
        )


def get_demo_dashboard_service() -> DashboardDataService:
    return DashboardDataService()


def normalize_promotion_id(value: str) -> str | None:
    try:
        return str(UUID(value)).lower()
    except ValueError:
        if value.startswith("promo-") and value[6:].isdigit():
            return value.lower()
        return None
