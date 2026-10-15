import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


async def request(path: str) -> tuple[int, dict | list]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def test_overview_returns_aggregated_synthetic_dashboard_data() -> None:
    status_code, body = await request("/api/v1/dashboard/overview")

    assert status_code == 200
    assert body["data_source"] == "synthetic_development"
    assert "Synthetic development data only" in body["disclaimer"]
    assert body["kpis"]["pending_my_approval"] == 6
    assert body["kpis"]["action_required"] == 4
    assert body["kpis"]["upcoming_promotions"] == 12
    assert body["kpis"]["upcoming_period_weeks"] == 4
    assert body["kpis"]["planned_promo_spend"] == 1_240_000
    assert len(body["pending_approvals"]) == 5
    assert body["planning_snapshot"]["baseline_volume"] == 420_000
    assert body["planning_snapshot"]["promo_uplift"] == 72_000
    assert body["planning_snapshot"]["total_forecast"] == 492_000
    assert len(body["planning_snapshot"]["weekly_data"]) == 6
    assert body["promotion_financials"]["negative_contribution_count"] == 2
    assert (
        body["integration_status"]["sap_promotions"]["status"] == "attention_required"
    )
    assert body["role_configuration"]["source"] == "not_configured"
    assert body["role_configuration"]["available_roles"] == []


async def test_worklist_filter_returns_negative_contribution_promotions() -> None:
    status_code, body = await request(
        "/api/v1/dashboard/worklist?filter=negative-contribution"
    )

    assert status_code == 200
    assert {promotion["promotion_id"] for promotion in body} == {
        "PROMO-1046",
        "PROMO-1051",
    }


async def test_worklist_rejects_unsupported_filter() -> None:
    status_code, body = await request("/api/v1/dashboard/worklist?filter=unbounded")

    assert status_code == 422
    assert body == {"detail": "Unsupported worklist filter."}


async def test_promotion_review_returns_pricing_and_validation_details() -> None:
    status_code, body = await request("/api/v1/promotions/promo-1046")

    assert status_code == 200
    assert body["promotion_id"] == "PROMO-1046"
    assert body["negative_contribution"] is True
    assert body["items"][0]["landed_price"] == 8.75
    assert body["items"][0]["spend_treatment"] == "On-invoice"
    assert body["validation_messages"] == ["Review unit cost basis before approval."]


async def test_promotion_review_returns_not_found_for_unknown_identifier() -> None:
    status_code, body = await request("/api/v1/promotions/not-a-promotion")

    assert status_code == 404
    assert body == {"detail": "Promotion not found."}


def test_upcoming_period_configuration_is_bounded_and_defaults_to_four_weeks() -> None:
    settings = Settings(_env_file=None)
    assert settings.dashboard_upcoming_period_weeks == 4

    with pytest.raises(ValidationError):
        Settings(_env_file=None, dashboard_upcoming_period_weeks=0)
