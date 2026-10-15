import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.database import SessionLocal
from app.models import (
    ActualSellIn,
    AppUser,
    Baseline,
    CustomerL04,
    Listing,
    Market,
    MaterialP10,
    P09P10Split,
    ProductHierarchy,
    ProductP09,
    Promotion,
    PromotionItem,
    PromotionStatusLog,
    Tactic,
    UserAssignment,
)

MARKETS = [
    ("DE", "Germany", "VOL", "DE10"),
    ("ES", "Spain", "VOL", "ES10"),
    ("PT", "Portugal", "VOL", "PT10"),
    ("CH", "Switzerland", "PROMO", "CH10"),
    ("NL", "Netherlands", "PROMO", "NL10"),
    ("AT", "Austria", "PROMO", "AT10"),
    ("BE", "Belgium", "PROMO", "BE10"),
]
ACCOUNTS = [
    ("ROSSMANN", "Rossmann"),
    ("KAUFLAND", "Kaufland"),
    ("AMAZON", "Amazon"),
    ("EDEKA-NORD", "Edeka Nord"),
    ("NORMA", "Norma"),
    ("MUELLER", "Müller"),
]
BRANDS = ["Kleenex", "Scottex", "Hakle", "Huggies"]
PRODUCTS = [
    ("P09-1001", "Kleenex Facial Tissues 3-ply", "Kleenex", "Original", "Facial Tissue", 2),
    ("P09-1002", "Kleenex Balsam Tissues", "Kleenex", "Balsam", "Facial Tissue", 1),
    ("P09-1003", "Kleenex Ultra Soft Pocket", "Kleenex", "Ultra Soft", "Pocket Tissue", 3),
    ("P09-1004", "Kleenex Collection Cube", "Kleenex", "Collection", "Facial Tissue", 1),
    ("P09-2001", "Scottex Original Toilet Tissue", "Scottex", "Original", "Toilet Tissue", 2),
    ("P09-2002", "Scottex Sensitive Toilet Tissue", "Scottex", "Sensitive", "Toilet Tissue", 1),
    ("P09-2003", "Scottex Fresh Toilet Tissue", "Scottex", "Fresh", "Toilet Tissue", 3),
    ("P09-3001", "Hakle Classic Toilet Tissue", "Hakle", "Classic", "Toilet Tissue", 1),
    ("P09-3002", "Hakle Naturel Toilet Tissue", "Hakle", "Naturel", "Toilet Tissue", 2),
    ("P09-3003", "Hakle Feucht Fresh", "Hakle", "Feucht", "Moist Tissue", 1),
    ("P09-4001", "Huggies Extra Care Size 3", "Huggies", "Extra Care", "Diapers", 2),
    ("P09-4002", "Huggies Extra Care Size 4", "Huggies", "Extra Care", "Diapers", 1),
    ("P09-4003", "Huggies Little Swimmers", "Huggies", "Swimmers", "Swim Pants", 3),
    ("P09-4004", "Huggies Baby Wipes Pure", "Huggies", "Pure", "Baby Wipes", 2),
    ("P09-4005", "Huggies Baby Wipes Natural", "Huggies", "Natural Care", "Baby Wipes", 1),
]
TACTICS = ["Feature", "Display", "Price Promotion", "Coupon"]
USERS = [
    (os.getenv("SEED_ADMIN_EMAIL", "admin@arba.local"), "ArBa Admin", "ADMIN"),
    (os.getenv("SEED_PLANNER_EMAIL", "planner@arba.local"), "Demo Planner", "PLANNER"),
    (os.getenv("SEED_APPROVER_EMAIL", "approver@arba.local"), "Demo Approver", "APPROVER"),
    (os.getenv("SEED_VIEWER_EMAIL", "viewer@arba.local"), "Demo Viewer", "VIEWER"),
]


def monday_of_week(day: date) -> date:
    return day - timedelta(days=day.weekday())


async def seed() -> None:
    password = os.getenv("SEED_PASSWORD")
    if not password or len(password) < 12:
        raise ValueError("Set SEED_PASSWORD to a private value of at least 12 characters")

    async with SessionLocal() as session, session.begin():
        markets: dict[str, Market] = {}
        for code, name, mode, sales_org in MARKETS:
            market = await session.get(Market, code)
            if market is None:
                market = Market(
                    code=code,
                    name=name,
                    plan_mode=mode,
                    p10_sales_org=sales_org,
                    horizon_weeks=52,
                    active=True,
                )
                session.add(market)
            else:
                market.name, market.plan_mode = name, mode
                market.p10_sales_org, market.horizon_weeks, market.active = sales_org, 52, True
            markets[code] = market
        await session.flush()

        customers: dict[tuple[str, str], CustomerL04] = {}
        for market_code, *_ in MARKETS:
            for account_code, account_name in ACCOUNTS:
                customer = await session.scalar(
                    select(CustomerL04).where(
                        CustomerL04.market_code == market_code,
                        CustomerL04.name == account_name,
                    )
                )
                if customer is None:
                    customer = CustomerL04(
                        market_code=market_code,
                        name=account_name,
                        parent_l03=f"{market_code}-L03-01",
                        active=True,
                    )
                    session.add(customer)
                    await session.flush()
                customers[(market_code, account_code)] = customer

        await seed_products(session)
        for market_code, _, mode, _ in MARKETS:
            if mode == "PROMO":
                for tactic in TACTICS:
                    if await session.get(Tactic, (market_code, tactic)) is None:
                        session.add(Tactic(market_code=market_code, name=tactic, active=True))

        users: dict[str, AppUser] = {}
        for email, name, role in USERS:
            email = email.lower()
            user = await session.scalar(select(AppUser).where(AppUser.email == email))
            if user is None:
                user = AppUser(
                    email=email,
                    name=name,
                    role=role,
                    password_hash=hash_password(password),
                    active=True,
                )
                session.add(user)
            else:
                user.name, user.role = name, role
                user.password_hash, user.active = hash_password(password), True
            users[role] = user
        await session.flush()

        for (market_code, _), customer in customers.items():
            for role in ("PLANNER", "APPROVER", "VIEWER"):
                user = users[role]
                if await session.get(UserAssignment, (user.id, market_code, customer.id)) is None:
                    session.add(
                        UserAssignment(
                            user_id=user.id,
                            market_code=market_code,
                            customer_id=customer.id,
                        )
                    )
        await session.flush()

        customer_rows = [
            (market_code, account_code, customer.id)
            for (market_code, account_code), customer in customers.items()
        ]
        await seed_volumes(session, customer_rows)
        await seed_promotions(session, customers, users)


async def seed_products(session: AsyncSession) -> None:
    parent_by_brand: dict[str, str | None] = {brand: None for brand in BRANDS}
    for level in range(1, 9):
        for brand in BRANDS:
            node_id = f"P{level}-{brand.upper().replace(' ', '-')}"
            if await session.get(ProductHierarchy, node_id) is None:
                session.add(
                    ProductHierarchy(
                        node_id=node_id,
                        parent_id=parent_by_brand[brand],
                        level=level,
                        code=f"{brand[:3].upper()}-{level}",
                        text=f"{brand} level {level}",
                    )
                )
        await session.flush()
        parent_by_brand = {brand: f"P{level}-{brand.upper().replace(' ', '-')}" for brand in BRANDS}

    for p09_code, description, brand, sub_brand, category, material_count in PRODUCTS:
        if await session.get(ProductHierarchy, p09_code) is None:
            session.add(
                ProductHierarchy(
                    node_id=p09_code,
                    parent_id=parent_by_brand[brand],
                    level=9,
                    code=p09_code,
                    text=description,
                )
            )
        if await session.get(ProductP09, p09_code) is None:
            session.add(
                ProductP09(
                    code=p09_code,
                    description=description,
                    brand=brand,
                    sub_brand=sub_brand,
                    category=category,
                    hierarchy_node_id=p09_code,
                    active=True,
                )
            )
        await session.flush()
        split_values = [Decimal(100) / material_count] * material_count
        split_values[-1] = Decimal(100) - sum(split_values[:-1])
        for index, share in enumerate(split_values, start=1):
            material_code = f"MAT-{p09_code[-4:]}-{index:02d}"
            if await session.get(MaterialP10, material_code) is None:
                session.add(
                    MaterialP10(
                        material=material_code,
                        description=f"{description} order material {index}",
                        p09_code=p09_code,
                        case_uom="CS",
                        active=True,
                    )
                )
            valid_from = date.today()
            if await session.get(P09P10Split, (p09_code, material_code, valid_from)) is None:
                session.add(
                    P09P10Split(
                        p09_code=p09_code,
                        material=material_code,
                        valid_from=valid_from,
                        share=share,
                        source="CALC",
                    )
                )
        await session.flush()


async def execute_batches(
    session: AsyncSession, model: type, rows: list[dict[str, object]], batch_size: int = 1000
) -> None:
    for offset in range(0, len(rows), batch_size):
        statement = (
            insert(model).values(rows[offset : offset + batch_size]).on_conflict_do_nothing()
        )
        await session.execute(statement)


async def seed_volumes(session: AsyncSession, customers: list[tuple[str, str, int]]) -> None:
    product_codes = [product[0] for product in PRODUCTS]
    current_monday = monday_of_week(date.today())
    history = [
        (current_monday - timedelta(weeks=offset)).strftime("%G-W%V") for offset in range(52, 0, -1)
    ]
    horizon = [
        (current_monday + timedelta(weeks=offset)).strftime("%G-W%V") for offset in range(52)
    ]
    listing_rows: list[dict[str, object]] = []
    actual_rows: list[dict[str, object]] = []
    baseline_rows: list[dict[str, object]] = []
    mode_by_market = {code: mode for code, _, mode, _ in MARKETS}

    for market_code, _, customer_id in customers:
        for product_index, p09_code in enumerate(product_codes):
            listing_rows.append(
                {
                    "market_code": market_code,
                    "customer_id": customer_id,
                    "p09_code": p09_code,
                    "created_by": "seed",
                }
            )
            for week_index, iso_week in enumerate(history):
                actual_rows.append(
                    {
                        "market_code": market_code,
                        "customer_id": customer_id,
                        "p09_code": p09_code,
                        "iso_week": iso_week,
                        "qty_cs": Decimal(20 + product_index * 3 + week_index % 11),
                    }
                )
            if mode_by_market[market_code] == "VOL":
                for week_index, iso_week in enumerate(horizon):
                    baseline_rows.append(
                        {
                            "market_code": market_code,
                            "customer_id": customer_id,
                            "p09_code": p09_code,
                            "iso_week": iso_week,
                            "qty_cs": Decimal(40 + product_index * 4 + week_index % 9),
                            "source": "MANUAL",
                            "changed_by": "seed",
                        }
                    )
    await execute_batches(session, Listing, listing_rows)
    await execute_batches(session, ActualSellIn, actual_rows)
    await execute_batches(session, Baseline, baseline_rows)


async def seed_promotions(
    session: AsyncSession,
    customers: dict[tuple[str, str], CustomerL04],
    users: dict[str, AppUser],
) -> None:
    promo_markets = [code for code, _, mode, _ in MARKETS if mode == "PROMO"]
    current_monday = monday_of_week(date.today())
    statuses = ["NEW", "SAVED", "CHANGED", "APPROVED"]
    for index, promo_status in enumerate(statuses):
        promo_number = f"PR{index + 1:06d}"
        if await session.scalar(select(Promotion.id).where(Promotion.promo_number == promo_number)):
            continue
        market_code = promo_markets[index % len(promo_markets)]
        customer = customers[(market_code, ACCOUNTS[index][0])]
        start = current_monday + timedelta(weeks=index + 4)
        end = start + timedelta(days=6)
        promotion = Promotion(
            promo_number=promo_number,
            market_code=market_code,
            customer_id=customer.id,
            start_date=start,
            end_date=end,
            cons_start=start,
            cons_end=end,
            tactic=TACTICS[index % len(TACTICS)],
            status=promo_status,
            created_by=users["PLANNER"].email,
            approved_by=users["APPROVER"].email if promo_status == "APPROVED" else None,
            approved_at=datetime.now(UTC) if promo_status == "APPROVED" else None,
            version=1,
        )
        session.add(promotion)
        await session.flush()
        session.add_all(
            [
                PromotionStatusLog(
                    promotion_id=promotion.id,
                    user=users["PLANNER"].email,
                    old_status=None,
                    new_status=promo_status,
                ),
                PromotionItem(
                    promotion_id=promotion.id,
                    p09_code=PRODUCTS[index][0],
                    total_cs=Decimal(200 + index * 25),
                ),
            ]
        )


if __name__ == "__main__":
    asyncio.run(seed())
