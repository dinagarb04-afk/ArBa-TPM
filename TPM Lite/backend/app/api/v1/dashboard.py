from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.dashboard import DashboardOverview, PendingPromotion, PromotionDetail
from app.services.dashboard import get_demo_dashboard_service, normalize_promotion_id

router = APIRouter(tags=["dashboard"])


@router.get(
    "/dashboard/overview",
    response_model=DashboardOverview,
    summary="Get aggregated promotion overview",
)
async def dashboard_overview() -> DashboardOverview:
    return get_demo_dashboard_service().overview()


@router.get(
    "/dashboard/worklist",
    response_model=list[PendingPromotion],
    summary="Get synthetic filtered promotion worklist",
)
async def dashboard_worklist(
    filter_name: str = Query(default="all", alias="filter"),
) -> list[PendingPromotion]:
    allowed_filters = {
        "all",
        "pending-approval",
        "action-required",
        "upcoming",
        "negative-contribution",
        "planned-spend",
    }
    if filter_name not in allowed_filters:
        raise HTTPException(
            status_code=422,
            detail="Unsupported worklist filter.",
        )
    return get_demo_dashboard_service().worklist(filter_name)


@router.get(
    "/promotions/{promotion_id}",
    response_model=PromotionDetail,
    summary="Get synthetic promotion review details",
)
async def promotion_detail(promotion_id: str) -> PromotionDetail:
    normalized_id = normalize_promotion_id(promotion_id)
    promotion = (
        get_demo_dashboard_service().promotion_detail(normalized_id)
        if normalized_id is not None
        else None
    )
    if promotion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promotion not found.",
        )
    return promotion
