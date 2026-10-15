"""
ArBa Promo Volume Predictor - single-file local web application.

Run with: python "ArBa Volume Planner.py"
The first run creates a local SQLite database and prints a one-time password.
Set ARBA_DB_PATH and ARBA_SECRET to configure the database and signing key.
"""

from __future__ import annotations

import asyncio
import base64
import calendar
import csv
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request as URLRequest
from urllib.request import urlopen
from uuid import UUID
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

APP_TITLE = "ArBa Promo Volume Predictor"
API_PREFIX = "/api/v1"
MARKETS = (
    ("DE", "Germany", "VOL", "DE10"),
    ("ES", "Spain", "VOL", "ES10"),
    ("PT", "Portugal", "VOL", "PT10"),
    ("CH", "Switzerland", "PROMO", "CH10"),
    ("NL", "Netherlands", "PROMO", "NL10"),
    ("AT", "Austria", "PROMO", "AT10"),
    ("BE", "Belgium", "PROMO", "BE10"),
)
ACCOUNTS = (
    ("ROSSMANN", "Rossmann"),
    ("KAUFLAND", "Kaufland"),
    ("AMAZON", "Amazon"),
    ("EDEKA-NORD", "Edeka Nord"),
    ("NORMA", "Norma"),
    ("MUELLER", "Müller"),
)
PRODUCTS = (
    (
        "P09-1001",
        "Kleenex Facial Tissues 3-ply",
        "Kleenex",
        "Original",
        "Facial Tissue",
        2,
    ),
    ("P09-1002", "Kleenex Balsam Tissues", "Kleenex", "Balsam", "Facial Tissue", 1),
    (
        "P09-1003",
        "Kleenex Ultra Soft Pocket",
        "Kleenex",
        "Ultra Soft",
        "Pocket Tissue",
        3,
    ),
    (
        "P09-1004",
        "Kleenex Collection Cube",
        "Kleenex",
        "Collection",
        "Facial Tissue",
        1,
    ),
    (
        "P09-2001",
        "Scottex Original Toilet Tissue",
        "Scottex",
        "Original",
        "Toilet Tissue",
        2,
    ),
    (
        "P09-2002",
        "Scottex Sensitive Toilet Tissue",
        "Scottex",
        "Sensitive",
        "Toilet Tissue",
        1,
    ),
    ("P09-2003", "Scottex Fresh Toilet Tissue", "Scottex", "Fresh", "Toilet Tissue", 3),
    ("P09-3001", "Hakle Classic Toilet Tissue", "Hakle", "Classic", "Toilet Tissue", 1),
    ("P09-3002", "Hakle Naturel Toilet Tissue", "Hakle", "Naturel", "Toilet Tissue", 2),
    ("P09-3003", "Hakle Feucht Fresh", "Hakle", "Feucht", "Moist Tissue", 1),
    ("P09-4001", "Huggies Extra Care Size 3", "Huggies", "Extra Care", "Diapers", 2),
    ("P09-4002", "Huggies Extra Care Size 4", "Huggies", "Extra Care", "Diapers", 1),
    ("P09-4003", "Huggies Little Swimmers", "Huggies", "Swimmers", "Swim Pants", 3),
    ("P09-4004", "Huggies Baby Wipes Pure", "Huggies", "Pure", "Baby Wipes", 2),
    (
        "P09-4005",
        "Huggies Baby Wipes Natural",
        "Huggies",
        "Natural Care",
        "Baby Wipes",
        1,
    ),
)
TACTICS = ("Feature", "Display", "Price Promotion", "Coupon")
PIPELINES = (
    (
        "IN-01",
        "S/4 Customer Master",
        "INBOUND",
        "SAP S/4HANA",
        "ArBa",
        "MockSapConnector",
    ),
    (
        "IN-02",
        "S/4 Product Master",
        "INBOUND",
        "SAP S/4HANA",
        "ArBa",
        "MockSapConnector",
    ),
    (
        "IN-03",
        "S/4 Sell-in Actuals",
        "INBOUND",
        "SAP S/4HANA",
        "ArBa",
        "MockSapConnector",
    ),
    (
        "IN-04",
        "P09 to P10 Split Recalculation",
        "INBOUND",
        "ArBa Actuals",
        "ArBa",
        "MockSapConnector",
    ),
    (
        "OUT-01",
        "ArBa Weekly Volume Feed",
        "OUTBOUND",
        "ArBa",
        "P10 Arete",
        "MockP10Connector",
    ),
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("arba")
DB_PATH = Path(os.getenv("ARBA_DB_PATH", Path(__file__).with_name("arba_volume_planner.sqlite3")))
FILE_ROOT = Path(os.getenv("ARBA_FILES_DIR", DB_PATH.parent / "arba_files"))
INBOUND_QUEUE_DIR = FILE_ROOT / "Inbound Queue"
INBOUND_PROCESSED_DIR = FILE_ROOT / "Inbound Processed"
OUTBOUND_DIR = FILE_ROOT / "Outbound"
DB_LOCK = threading.RLock()
SIGNING_SECRET = os.getenv("ARBA_SECRET", "")
if not SIGNING_SECRET:
    SIGNING_SECRET = secrets.token_urlsafe(48)
SSO_STATE_COOKIE = "arba_sso_state"


def configured_pipeline_path(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    root = FILE_ROOT.resolve()
    supplied = Path(value.strip())
    if supplied.is_absolute():
        raise HTTPException(status_code=422, detail="Pipeline file location must be relative to ArBa Files")
    resolved = (root / supplied).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Pipeline file location must stay within ArBa Files") from exc
    return resolved


def validate_pipeline_file_location(value: str | None, direction: str) -> Path | None:
    resolved = configured_pipeline_path(value)
    if resolved is None:
        return None
    expected_parent = (INBOUND_QUEUE_DIR if direction == "INBOUND" else OUTBOUND_DIR).resolve()
    if resolved.parent != expected_parent:
        folder = "Inbound Queue" if direction == "INBOUND" else "Outbound"
        raise HTTPException(
            status_code=422,
            detail=f"{direction} pipeline files must be directly inside the {folder} folder",
        )
    return resolved
SSO_SCOPES = "openid profile email User.Read"


class SSOAuthenticationError(Exception):
    pass


def entra_sso_config() -> dict[str, str] | None:
    required = {
        "tenant_id": os.getenv("ARBA_ENTRA_TENANT_ID", "").strip(),
        "client_id": os.getenv("ARBA_ENTRA_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("ARBA_ENTRA_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("ARBA_ENTRA_REDIRECT_URI", "").strip(),
    }
    if not all(required.values()):
        return None
    return required


def signed_sso_state(state: str, verifier: str) -> str:
    payload = f"{state}:{verifier}"
    signature = hmac.new(SIGNING_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_sso_state(cookie: str | None, state: str) -> str | None:
    if not cookie:
        return None
    try:
        cookie_state, verifier, signature = cookie.split(":", maxsplit=2)
    except ValueError:
        return None
    payload = f"{cookie_state}:{verifier}"
    expected = hmac.new(SIGNING_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected) or not hmac.compare_digest(cookie_state, state):
        return None
    return verifier


def sso_http_json(url: str, data: dict[str, str] | None = None, access_token: str | None = None) -> Any:
    body = urlencode(data).encode() if data is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = URLRequest(url, data=body, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Entra SSO request failed: %s", type(exc).__name__)
        raise SSOAuthenticationError("The identity provider could not complete sign-in") from exc


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_monday(week: str) -> date:
    try:
        year_text, week_text = week.split("-W", maxsplit=1)
        return date.fromisocalendar(int(year_text), int(week_text), 1)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid ISO week: {week}") from exc


def future_weeks(count: int = 52) -> list[str]:
    current = date.today()
    monday = current - timedelta(days=current.weekday())
    return [iso_week(monday + timedelta(weeks=offset)) for offset in range(count)]


def historical_weeks(count: int = 52) -> list[str]:
    current = date.today()
    monday = current - timedelta(days=current.weekday())
    return [iso_week(monday - timedelta(weeks=offset)) for offset in range(count, 0, -1)]


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", maxsplit=1)
        candidate = password_hash(password, bytes.fromhex(salt_hex)).split("$", maxsplit=1)[1]
        return hmac.compare_digest(candidate, digest_hex)
    except (ValueError, TypeError):
        return False


def sign_session(user_id: int, role: str, expires: int) -> str:
    payload = f"{user_id}:{role}:{expires}"
    signature = hmac.new(SIGNING_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_session(value: str) -> tuple[int, str] | None:
    try:
        user_text, role, expires_text, signature = value.split(":", maxsplit=3)
        payload = f"{user_text}:{role}:{expires_text}"
        expected = hmac.new(SIGNING_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature) or int(expires_text) < int(
            utcnow().timestamp()
        ):
            return None
        return int(user_text), role
    except (ValueError, TypeError):
        return None


def create_schema_and_seed() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS market (
                code TEXT PRIMARY KEY, name TEXT NOT NULL,
                plan_mode TEXT NOT NULL CHECK(plan_mode IN ('VOL','PROMO')),
                p10_sales_org TEXT NOT NULL, horizon_weeks INTEGER NOT NULL DEFAULT 52,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS customer_l04 (
                id INTEGER PRIMARY KEY AUTOINCREMENT, market_code TEXT NOT NULL REFERENCES market(code),
                name TEXT NOT NULL, parent_l03 TEXT, active INTEGER NOT NULL DEFAULT 1,
                source_updated_at TEXT, external_code TEXT, UNIQUE(market_code,name), UNIQUE(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS product_hierarchy (
                node_id TEXT PRIMARY KEY, parent_id TEXT REFERENCES product_hierarchy(node_id),
                level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 9), code TEXT NOT NULL, text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS product_p09 (
                code TEXT PRIMARY KEY, description TEXT NOT NULL, brand TEXT NOT NULL,
                sub_brand TEXT NOT NULL, category TEXT NOT NULL,
                hierarchy_node_id TEXT NOT NULL REFERENCES product_hierarchy(node_id),
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS material_p10 (
                material TEXT PRIMARY KEY, description TEXT NOT NULL,
                p09_code TEXT NOT NULL REFERENCES product_p09(code),
                case_uom TEXT NOT NULL DEFAULT 'CS', active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS p09_p10_split (
                p09_code TEXT NOT NULL REFERENCES product_p09(code),
                material TEXT NOT NULL REFERENCES material_p10(material),
                share REAL NOT NULL CHECK(share >= 0 AND share <= 100),
                valid_from TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('CALC','MANUAL')),
                PRIMARY KEY(p09_code,material,valid_from)
            );
            CREATE TABLE IF NOT EXISTS tactic (
                market_code TEXT NOT NULL REFERENCES market(code), name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(market_code,name)
            );
            CREATE TABLE IF NOT EXISTS app_user (
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('PLANNER','APPROVER','ADMIN','VIEWER')),
                password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                is_seed INTEGER NOT NULL DEFAULT 0,
                sso_subject TEXT, last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS user_assignment (
                user_id INTEGER NOT NULL REFERENCES app_user(id), market_code TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                PRIMARY KEY(user_id,market_code,customer_id),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS user_sales_org (
                user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                sales_org TEXT NOT NULL, PRIMARY KEY(user_id,sales_org)
            );
            CREATE TABLE IF NOT EXISTS user_sales_org_admin (
                user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                sales_org TEXT NOT NULL,
                PRIMARY KEY(user_id,sales_org)
            );
            CREATE TABLE IF NOT EXISTS listing (
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL, p09_code TEXT NOT NULL REFERENCES product_p09(code),
                created_by TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(market_code,customer_id,p09_code),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS baseline (
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL, p09_code TEXT NOT NULL REFERENCES product_p09(code),
                iso_week TEXT NOT NULL, qty_cs REAL NOT NULL CHECK(qty_cs >= 0),
                source TEXT NOT NULL CHECK(source IN ('MANUAL','UPLOAD')),
                changed_by TEXT NOT NULL, changed_at TEXT NOT NULL,
                PRIMARY KEY(market_code,customer_id,p09_code,iso_week),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS actual_sellin (
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL, p09_code TEXT NOT NULL REFERENCES product_p09(code),
                iso_week TEXT NOT NULL, qty_cs REAL NOT NULL CHECK(qty_cs >= 0), loaded_at TEXT NOT NULL,
                PRIMARY KEY(market_code,customer_id,p09_code,iso_week),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id)
            );
            CREATE TABLE IF NOT EXISTS promotion (
                id INTEGER PRIMARY KEY AUTOINCREMENT, promo_number TEXT UNIQUE NOT NULL,
                market_code TEXT NOT NULL, customer_id INTEGER NOT NULL,
                start_date TEXT NOT NULL, end_date TEXT NOT NULL, cons_start TEXT NOT NULL, cons_end TEXT NOT NULL,
                tactic TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('NEW','SAVED','CHANGED','APPROVED')),
                created_by TEXT NOT NULL, created_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT,
                version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
                CHECK(end_date >= start_date), CHECK(cons_end >= cons_start),
                FOREIGN KEY(market_code,customer_id) REFERENCES customer_l04(market_code,id),
                FOREIGN KEY(market_code,tactic) REFERENCES tactic(market_code,name)
            );
            CREATE TABLE IF NOT EXISTS promotion_item (
                promotion_id INTEGER NOT NULL REFERENCES promotion(id) ON DELETE CASCADE,
                p09_code TEXT NOT NULL REFERENCES product_p09(code),
                total_cs REAL NOT NULL CHECK(total_cs >= 0), PRIMARY KEY(promotion_id,p09_code)
            );
            CREATE TABLE IF NOT EXISTS promotion_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, promotion_id INTEGER NOT NULL REFERENCES promotion(id),
                ts TEXT NOT NULL, user TEXT NOT NULL, old_status TEXT, new_status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pipeline (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, direction TEXT NOT NULL,
                source TEXT NOT NULL, target TEXT NOT NULL, connector_type TEXT NOT NULL,
                schedule_cron TEXT, enabled INTEGER NOT NULL DEFAULT 0, config_json TEXT NOT NULL DEFAULT '{}',
                schedule_frequency TEXT NOT NULL DEFAULT 'DAILY', schedule_timezone TEXT NOT NULL DEFAULT 'UTC',
                schedule_time TEXT NOT NULL DEFAULT '02:00', schedule_weekday INTEGER NOT NULL DEFAULT 1,
                schedule_month_day INTEGER NOT NULL DEFAULT 1, schedule_quarter_month INTEGER NOT NULL DEFAULT 1,
                schedule_start_date TEXT, schedule_end_date TEXT, last_schedule_key TEXT
            );
            CREATE TABLE IF NOT EXISTS pipeline_run (
                id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline_id TEXT NOT NULL REFERENCES pipeline(id),
                trigger TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                rows_read INTEGER NOT NULL DEFAULT 0, rows_written INTEGER NOT NULL DEFAULT 0,
                rows_rejected INTEGER NOT NULL DEFAULT 0, message TEXT, file_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS pipeline_run_error (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES pipeline_run(id),
                row_no INTEGER NOT NULL, key TEXT, error TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS p10_outbound (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES pipeline_run(id),
                market_code TEXT NOT NULL REFERENCES market(code), start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                plan_account TEXT NOT NULL, material TEXT NOT NULL, base INTEGER NOT NULL,
                lift INTEGER NOT NULL, total INTEGER NOT NULL CHECK(total=base+lift),
                promo_number TEXT NOT NULL, cons_start TEXT NOT NULL, cons_end TEXT NOT NULL, sales_org TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
                action TEXT NOT NULL, user TEXT NOT NULL, ts TEXT NOT NULL,
                before_json TEXT, after_json TEXT
            );
            CREATE TABLE IF NOT EXISTS managed_file (
                id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT NOT NULL,
                category TEXT NOT NULL, original_name TEXT NOT NULL, stored_path TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, uploaded_by TEXT NOT NULL, created_at TEXT NOT NULL,
                processed_at TEXT, row_count INTEGER NOT NULL DEFAULT 0, message TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_baseline_market_customer_week
                ON baseline(market_code,customer_id,iso_week);
            CREATE INDEX IF NOT EXISTS ix_actual_market_customer_week
                ON actual_sellin(market_code,customer_id,iso_week);
            CREATE INDEX IF NOT EXISTS ix_promotion_account_dates
                ON promotion(market_code,customer_id,start_date,end_date);
            """
        )
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(app_user)")}
        if "sso_subject" not in user_columns:
            db.execute("ALTER TABLE app_user ADD COLUMN sso_subject TEXT")
        if "is_seed" not in user_columns:
            db.execute("ALTER TABLE app_user ADD COLUMN is_seed INTEGER NOT NULL DEFAULT 0")
        if "last_login_at" not in user_columns:
            db.execute("ALTER TABLE app_user ADD COLUMN last_login_at TEXT")
        db.execute(
            "UPDATE app_user SET last_login_at=? WHERE last_login_at IS NULL",
            (utcnow().isoformat(),),
        )
        db.execute(
            "UPDATE app_user SET is_seed=1 WHERE email IN "
            "('admin@arba.local','planner@arba.local','approver@arba.local','viewer@arba.local')"
        )
        customer_columns = {row["name"] for row in db.execute("PRAGMA table_info(customer_l04)")}
        if "external_code" not in customer_columns:
            db.execute("ALTER TABLE customer_l04 ADD COLUMN external_code TEXT")
        pipeline_columns = {row["name"] for row in db.execute("PRAGMA table_info(pipeline)")}
        pipeline_migrations = {
            "schedule_frequency": "TEXT NOT NULL DEFAULT 'DAILY'",
            "schedule_timezone": "TEXT NOT NULL DEFAULT 'UTC'",
            "schedule_time": "TEXT NOT NULL DEFAULT '02:00'",
            "schedule_weekday": "INTEGER NOT NULL DEFAULT 1",
            "schedule_month_day": "INTEGER NOT NULL DEFAULT 1",
            "schedule_quarter_month": "INTEGER NOT NULL DEFAULT 1",
            "schedule_start_date": "TEXT",
            "schedule_end_date": "TEXT",
            "last_schedule_key": "TEXT",
        }
        for column, definition in pipeline_migrations.items():
            if column not in pipeline_columns:
                db.execute(f"ALTER TABLE pipeline ADD COLUMN {column} {definition}")
        db.execute(
            "INSERT OR IGNORE INTO user_sales_org(user_id,sales_org) "
            "SELECT DISTINCT ua.user_id,m.p10_sales_org FROM user_assignment ua "
            "JOIN market m ON m.code=ua.market_code"
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_app_user_sso_subject "
            "ON app_user(sso_subject) WHERE sso_subject IS NOT NULL"
        )
        db.executemany(
            "INSERT OR IGNORE INTO tactic(market_code,name) VALUES(?,?)",
            [
                (market["code"], tactic)
                for market in db.execute("SELECT code FROM market WHERE active=1")
                for tactic in TACTICS
            ],
        )
        if db.execute("SELECT 1 FROM market LIMIT 1").fetchone():
            return
        seed_database(db)


def seed_database(db: sqlite3.Connection) -> None:
    db.executemany(
        "INSERT INTO market(code,name,plan_mode,p10_sales_org,horizon_weeks) VALUES(?,?,?,?,52)",
        MARKETS,
    )
    accounts: dict[tuple[str, str], int] = {}
    for market_code, _, _, _ in MARKETS:
        for account_code, account_name in ACCOUNTS:
            cursor = db.execute(
                "INSERT INTO customer_l04(market_code,name,parent_l03) VALUES(?,?,?)",
                (market_code, account_name, f"{market_code}-L03-01"),
            )
            accounts[(market_code, account_code)] = int(cursor.lastrowid)

    brands = sorted({product[2] for product in PRODUCTS})
    for brand in brands:
        parent: str | None = None
        for level in range(1, 9):
            node_id = f"P{level}-{brand.upper().replace(' ', '-')}"
            db.execute(
                "INSERT INTO product_hierarchy(node_id,parent_id,level,code,text) VALUES(?,?,?,?,?)",
                (
                    node_id,
                    parent,
                    level,
                    f"{brand[:3].upper()}-{level}",
                    f"{brand} level {level}",
                ),
            )
            parent = node_id
        brand_parent[brand] = parent

    for code, description, brand, sub_brand, category, material_count in PRODUCTS:
        db.execute(
            "INSERT INTO product_hierarchy(node_id,parent_id,level,code,text) VALUES(?,?,9,?,?)",
            (code, brand_parent[brand], code, description),
        )
        db.execute(
            "INSERT INTO product_p09(code,description,brand,sub_brand,category,hierarchy_node_id) "
            "VALUES(?,?,?,?,?,?)",
            (code, description, brand, sub_brand, category, code),
        )
        for index in range(material_count):
            material = f"MAT-{code[-4:]}-{index + 1:02d}"
            share = 100 / material_count
            db.execute(
                "INSERT INTO material_p10(material,description,p09_code,case_uom) VALUES(?,?,?,'CS')",
                (material, f"{description} order material {index + 1}", code),
            )
            db.execute(
                "INSERT INTO p09_p10_split(p09_code,material,share,valid_from,source) "
                "VALUES(?,?,?,?, 'CALC')",
                (code, material, share, date.today().isoformat()),
            )

    for market, _, _, _ in MARKETS:
        db.executemany(
            "INSERT INTO tactic(market_code,name) VALUES(?,?)",
            [(market, tactic) for tactic in TACTICS],
        )

    initial_password = os.getenv("ARBA_INITIAL_PASSWORD")
    if not initial_password:
        initial_password = secrets.token_urlsafe(15)
        print(
            f"\nArBa first-run password (admin@arba.local): {initial_password}\n",
            flush=True,
        )
        print(
            "Use this password for the seeded demo users; set ARBA_INITIAL_PASSWORD to choose one.",
            flush=True,
        )
    if len(initial_password) < 12:
        raise ValueError("ARBA_INITIAL_PASSWORD must contain at least 12 characters")
    users = (
        ("admin@arba.local", "ArBa Administrator", "ADMIN"),
        ("planner@arba.local", "Demo Planner", "PLANNER"),
        ("approver@arba.local", "Demo Approver", "APPROVER"),
        ("viewer@arba.local", "Demo Viewer", "VIEWER"),
    )
    user_ids: dict[str, int] = {}
    for email, name, role in users:
        cursor = db.execute(
            "INSERT INTO app_user(email,name,role,password_hash,is_seed) VALUES(?,?,?,?,1)",
            (email, name, role, password_hash(initial_password)),
        )
        user_ids[role] = int(cursor.lastrowid)
    for role in ("PLANNER", "APPROVER", "VIEWER"):
        db.executemany(
            "INSERT INTO user_sales_org(user_id,sales_org) VALUES(?,?)",
            [(user_ids[role], sales_org) for _, _, _, sales_org in MARKETS],
        )
    for (market_code, _), customer_id in accounts.items():
        for role in ("PLANNER", "APPROVER", "VIEWER"):
            db.execute(
                "INSERT INTO user_assignment(user_id,market_code,customer_id) VALUES(?,?,?)",
                (user_ids[role], market_code, customer_id),
            )

    weeks_back, weeks_ahead = historical_weeks(), future_weeks()
    listed = [p[0] for p in PRODUCTS]
    now_text = utcnow().isoformat()
    for (market_code, _), customer_id in accounts.items():
        db.executemany(
            "INSERT INTO listing(market_code,customer_id,p09_code,created_by,created_at) "
            "VALUES(?,?,?,'seed',?)",
            [(market_code, customer_id, product, now_text) for product in listed],
        )
        actual_rows = []
        for p_index, product in enumerate(listed):
            for w_index, week in enumerate(weeks_back):
                actual_rows.append(
                    (
                        market_code,
                        customer_id,
                        product,
                        week,
                        20 + p_index * 3 + w_index % 11,
                        now_text,
                    )
                )
        db.executemany(
            "INSERT INTO actual_sellin(market_code,customer_id,p09_code,iso_week,qty_cs,loaded_at) "
            "VALUES(?,?,?,?,?,?)",
            actual_rows,
        )
        baseline_rows = []
        for p_index, product in enumerate(listed):
            for w_index, week in enumerate(weeks_ahead):
                baseline_rows.append(
                    (
                        market_code,
                        customer_id,
                        product,
                        week,
                        40 + p_index * 4 + w_index % 9,
                        "MANUAL",
                        "seed",
                        now_text,
                    )
                )
        db.executemany(
            "INSERT INTO baseline(market_code,customer_id,p09_code,iso_week,qty_cs,source,changed_by,changed_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            baseline_rows,
        )

    promo_markets = [m[0] for m in MARKETS if m[2] == "PROMO"]
    current_monday = date.today() - timedelta(days=date.today().weekday())
    for index, promo_status in enumerate(("NEW", "SAVED", "CHANGED", "APPROVED")):
        market = promo_markets[index]
        customer = accounts[(market, ACCOUNTS[index][0])]
        start = current_monday + timedelta(weeks=index + 4)
        end = start + timedelta(days=6)
        promo_number = f"PR{index + 1:06d}"
        cursor = db.execute(
            "INSERT INTO promotion(promo_number,market_code,customer_id,start_date,end_date,cons_start,cons_end,"
            "tactic,status,created_by,created_at,approved_by,approved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                promo_number,
                market,
                customer,
                start.isoformat(),
                end.isoformat(),
                start.isoformat(),
                end.isoformat(),
                TACTICS[index],
                promo_status,
                "planner@arba.local",
                now_text,
                "approver@arba.local" if promo_status == "APPROVED" else None,
                now_text if promo_status == "APPROVED" else None,
            ),
        )
        promo_id = int(cursor.lastrowid)
        log_status(db, promo_id, "planner@arba.local", None, "NEW")
        db.execute(
            "INSERT INTO promotion_item(promotion_id,p09_code,total_cs) VALUES(?,?,?)",
            (promo_id, PRODUCTS[index][0], 200 + index * 25),
        )
        db.execute(
            "INSERT INTO promotion_status_log(promotion_id,ts,user,old_status,new_status) VALUES(?,?,?,?,?)",
            (promo_id, now_text, "planner@arba.local", None, promo_status),
        )

    db.executemany(
        "INSERT INTO pipeline(id,name,direction,source,target,connector_type,schedule_cron,enabled) "
        "VALUES(?,?,?,?,?,?,?,1)",
        [
            (pid, name, direction, source, target, connector, "0 2 * * *")
            for pid, name, direction, source, target, connector in PIPELINES
        ],
    )
    db.commit()


# This name is filled during first-run seed creation.
brand_parent: dict[str, str | None] = {}


def get_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get("arba_session")
    session = verify_session(token) if token else None
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    user_id, _ = session
    with DB_LOCK, connect() as db:
        row = db.execute(
            "SELECT id,email,name,role,active FROM app_user WHERE id=?", (user_id,)
        ).fetchone()
        admin_sales_org_access = [
            item["sales_org"]
            for item in db.execute(
                "SELECT sales_org FROM user_sales_org_admin WHERE user_id=? ORDER BY sales_org",
                (user_id,),
            )
        ]
    if row is None or not row["active"]:
        raise HTTPException(status_code=401, detail="Account is inactive")
    return {**dict(row), "admin_sales_org_access": admin_sales_org_access}


CurrentUser = Annotated[dict[str, Any], Depends(get_user)]


def require_role(user: dict[str, Any], *roles: str) -> None:
    if user["role"] != "ADMIN" and user["role"] not in roles:
        raise HTTPException(status_code=403, detail="Your role cannot perform this action")


def require_access_administrator(user: dict[str, Any]) -> None:
    if user["role"] != "ADMIN" and not user.get("admin_sales_org_access"):
        raise HTTPException(status_code=403, detail="Sales organization administrator access is required")


def check_assignment(
    db: sqlite3.Connection, user: dict[str, Any], market: str, customer: int
) -> None:
    if user["role"] == "ADMIN":
        return
    market_row = db.execute(
        "SELECT p10_sales_org FROM market WHERE code=? AND active=1", (market,)
    ).fetchone()
    if market_row and market_row["p10_sales_org"] in user.get("admin_sales_org_access", []):
        return
    allowed = db.execute(
        "SELECT 1 FROM user_assignment ua "
        "JOIN market m ON m.code=ua.market_code "
        "JOIN user_sales_org so ON so.user_id=ua.user_id AND so.sales_org=m.p10_sales_org "
        "WHERE ua.user_id=? AND ua.market_code=? AND ua.customer_id=?",
        (user["id"], market, customer),
    ).fetchone()
    if not allowed:
        raise HTTPException(status_code=403, detail="Plan account is not assigned to your user")


def audit(
    db: sqlite3.Connection,
    entity: str,
    entity_id: str,
    action: str,
    user: str,
    before: Any = None,
    after: Any = None,
) -> None:
    db.execute(
        "INSERT INTO audit_log(entity,entity_id,action,user,ts,before_json,after_json) VALUES(?,?,?,?,?,?,?)",
        (
            entity,
            entity_id,
            action,
            user,
            utcnow().isoformat(),
            json.dumps(before, default=str) if before is not None else None,
            json.dumps(after, default=str) if after is not None else None,
        ),
    )


def log_status(db: sqlite3.Connection, promo_id: int, user: str, old: str | None, new: str) -> None:
    db.execute(
        "INSERT INTO promotion_status_log(promotion_id,ts,user,old_status,new_status) VALUES(?,?,?,?,?)",
        (promo_id, utcnow().isoformat(), user, old, new),
    )


class LoginPayload(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=256)


class SignupPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    email: str = Field(
        min_length=5,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str = Field(min_length=12, max_length=256)


class BaselineCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: str
    week: str
    qty_cs: float = Field(ge=0, le=1_000_000_000)


class BaselineSave(BaseModel):
    market: str
    customer_id: int
    cells: list[BaselineCell] = Field(max_length=20_000)


class PromoPayload(BaseModel):
    id: int | None = None
    version: int | None = None
    market: str
    customer_id: int
    start_date: date
    end_date: date
    cons_start: date
    cons_end: date
    tactic: str
    items: dict[str, float] = Field(min_length=1, max_length=100)


class ListingPayload(BaseModel):
    market: str
    customer_id: int
    products: list[str] = Field(max_length=500)


class PipelineUpdate(BaseModel):
    enabled: bool
    schedule_frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"]
    schedule_timezone: str = Field(min_length=1, max_length=100)
    schedule_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    schedule_weekday: int = Field(ge=0, le=6)
    schedule_month_day: int = Field(ge=1, le=31)
    schedule_quarter_month: int = Field(ge=1, le=3)
    schedule_start_date: date | None = None
    schedule_end_date: date | None = None
    file_path: str | None = Field(default=None, max_length=500)


class PipelineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    direction: Literal["INBOUND", "OUTBOUND"]
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    connector_type: Literal[
        "FileConnector",
        "MockSapConnector",
        "MockP10Connector",
        "SapOdataConnector",
        "SftpConnector",
        "RestConnector",
    ]
    file_path: str | None = Field(default=None, max_length=500)
    enabled: bool = False
    schedule_frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"] = "DAILY"
    schedule_timezone: str = "UTC"
    schedule_time: str = Field(default="02:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    schedule_weekday: int = Field(default=1, ge=0, le=6)
    schedule_month_day: int = Field(default=1, ge=1, le=31)
    schedule_quarter_month: int = Field(default=1, ge=1, le=3)
    schedule_start_date: date | None = None
    schedule_end_date: date | None = None


class UserAccessAssignment(BaseModel):
    market_code: str
    customer_id: int


class AdminUserUpdate(BaseModel):
    role: Literal["PLANNER", "APPROVER", "ADMIN", "VIEWER"]
    active: bool
    assignments: list[UserAccessAssignment] = Field(max_length=500)
    sales_org_access: list[str] = Field(max_length=100, default_factory=list)
    admin_sales_org_access: list[str] = Field(max_length=100, default_factory=list)


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=2, max_length=100)
    role: Literal["PLANNER", "APPROVER", "VIEWER"]
    password: str = Field(min_length=12, max_length=256)
    active: bool = True
    sales_org_access: list[str] = Field(max_length=100, default_factory=list)
    assignments: list[UserAccessAssignment] = Field(max_length=500)
    admin_sales_org_access: list[str] = Field(max_length=100, default_factory=list)


class MasterFileUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=15_000_000)


class BaselineFileUpload(MasterFileUpload):
    market: str
    customer_id: int


def schedule_due(pipeline: sqlite3.Row, now: datetime) -> tuple[bool, str]:
    try:
        zone = ZoneInfo(str(pipeline["schedule_timezone"]))
    except ZoneInfoNotFoundError as exc:
        logger.error("Invalid timezone for pipeline %s", pipeline["id"])
        raise ValueError(f"Unknown timezone: {pipeline['schedule_timezone']}") from exc
    local_now = now.astimezone(zone)
    if pipeline["schedule_start_date"] and local_now.date() < date.fromisoformat(pipeline["schedule_start_date"]):
        return False, f"not-started:{local_now.date()}"
    if pipeline["schedule_end_date"] and local_now.date() > date.fromisoformat(pipeline["schedule_end_date"]):
        return False, f"ended:{local_now.date()}"
    run_hour, run_minute = map(int, str(pipeline["schedule_time"]).split(":"))
    due = local_now.hour == run_hour and local_now.minute == run_minute
    frequency = pipeline["schedule_frequency"]
    if frequency == "WEEKLY":
        due = due and local_now.weekday() == int(pipeline["schedule_weekday"])
    elif frequency == "MONTHLY":
        due = due and local_now.day == min(
            int(pipeline["schedule_month_day"]),
            calendar.monthrange(local_now.year, local_now.month)[1],
        )
    elif frequency == "QUARTERLY":
        due = (
            due
            and (local_now.month - 1) % 3 + 1 == int(pipeline["schedule_quarter_month"])
            and local_now.day
            == min(
                int(pipeline["schedule_month_day"]),
                calendar.monthrange(local_now.year, local_now.month)[1],
            )
        )
    elif frequency != "DAILY":
        raise ValueError(f"Unknown pipeline schedule frequency: {frequency}")
    return due, f"{frequency}:{local_now:%Y-%m-%dT%H:%M}"


def next_pipeline_run(pipeline: sqlite3.Row, now: datetime | None = None) -> str | None:
    if not pipeline["enabled"]:
        return None
    try:
        zone = ZoneInfo(str(pipeline["schedule_timezone"]))
        local_now = (now or utcnow()).astimezone(zone)
        run_hour, run_minute = map(int, str(pipeline["schedule_time"]).split(":"))
        frequency = str(pipeline["schedule_frequency"])
        start_date = (
            date.fromisoformat(pipeline["schedule_start_date"])
            if pipeline["schedule_start_date"]
            else None
        )
        end_date = (
            date.fromisoformat(pipeline["schedule_end_date"])
            if pipeline["schedule_end_date"]
            else None
        )
        first_day = max(local_now.date(), start_date) if start_date else local_now.date()
        for offset in range(370):
            day = first_day + timedelta(days=offset)
            if end_date and day > end_date:
                return None
            if frequency == "WEEKLY" and day.weekday() != int(pipeline["schedule_weekday"]):
                continue
            if frequency == "MONTHLY":
                if day.day != min(
                    int(pipeline["schedule_month_day"]),
                    calendar.monthrange(day.year, day.month)[1],
                ):
                    continue
            elif frequency == "QUARTERLY":
                if (day.month - 1) % 3 + 1 != int(pipeline["schedule_quarter_month"]):
                    continue
                if day.day != min(
                    int(pipeline["schedule_month_day"]),
                    calendar.monthrange(day.year, day.month)[1],
                ):
                    continue
            elif frequency not in {"DAILY", "WEEKLY", "MONTHLY"}:
                return None
            candidate = datetime(
                day.year, day.month, day.day, run_hour, run_minute, tzinfo=zone
            )
            if candidate > local_now:
                return candidate.isoformat()
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return None


async def pipeline_scheduler() -> None:
    while True:
        try:
            scheduled: list[str] = []
            now = utcnow()
            with DB_LOCK, connect() as db:
                inactive_before = (now - timedelta(days=30)).isoformat()
                inactive_users = db.execute(
                    "SELECT id,email,last_login_at FROM app_user "
                    "WHERE active=1 AND last_login_at IS NOT NULL AND last_login_at<?",
                    (inactive_before,),
                ).fetchall()
                if inactive_users:
                    with db:
                        for inactive_user in inactive_users:
                            db.execute(
                                "UPDATE app_user SET active=0 WHERE id=? AND active=1",
                                (inactive_user["id"],),
                            )
                            if db.execute("SELECT changes()").fetchone()[0]:
                                audit(
                                    db,
                                    "app_user",
                                    str(inactive_user["id"]),
                                    "AUTO_DEACTIVATE_INACTIVE",
                                    "scheduler@arba.local",
                                    before={"active": True, "last_login_at": inactive_user["last_login_at"]},
                                    after={"active": False},
                                )
                for row in db.execute("SELECT * FROM pipeline WHERE enabled=1"):
                    try:
                        due, schedule_key = schedule_due(row, now)
                    except ValueError:
                        continue
                    if due and row["last_schedule_key"] != schedule_key:
                        with db:
                            db.execute(
                                "UPDATE pipeline SET last_schedule_key=? "
                                "WHERE id=? AND (last_schedule_key IS NULL OR last_schedule_key<>?)",
                                (schedule_key, row["id"], schedule_key),
                            )
                            if db.execute("SELECT changes()").fetchone()[0]:
                                scheduled.append(str(row["id"]))
            for pipeline_id in scheduled:
                try:
                    await run_pipeline(
                        pipeline_id,
                        {"id": 0, "role": "ADMIN", "email": "scheduler@arba.local"},
                        dry_run=False,
                        trigger="SCHEDULE",
                    )
                except Exception:
                    logger.exception("Scheduled pipeline %s failed to run", pipeline_id)
        except sqlite3.Error:
            logger.exception("Pipeline scheduler database error")
        await asyncio.sleep(20)


@asynccontextmanager
async def lifespan(_: FastAPI):
    for directory in (INBOUND_QUEUE_DIR, INBOUND_PROCESSED_DIR, OUTBOUND_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    create_schema_and_seed()
    scheduler = asyncio.create_task(pipeline_scheduler())
    try:
        yield
    finally:
        scheduler.cancel()
        try:
            await scheduler
        except asyncio.CancelledError:
            pass


app = FastAPI(title=APP_TITLE, version="1.0.0", lifespan=lifespan)
FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False),
    name="frontend-assets",
)


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.is_file():
        raise HTTPException(
            status_code=503,
            detail="React frontend is not built. Run `npm ci` and `npm run build` in frontend.",
        )
    return FileResponse(index_file)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{API_PREFIX}/auth/login")
async def login(payload: LoginPayload, response: Response) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute(
                "SELECT * FROM app_user WHERE email=? COLLATE NOCASE",
                (payload.email.strip().lower(),),
            ).fetchone()
            authenticated = (
                row is not None
                and bool(row["active"])
                and verify_password(payload.password, row["password_hash"])
            )
            if authenticated:
                db.execute(
                    "UPDATE app_user SET last_login_at=? WHERE id=?",
                    (utcnow().isoformat(), row["id"]),
                )
                row = db.execute("SELECT * FROM app_user WHERE id=?", (row["id"],)).fetchone()
                admin_sales_org_access = [
                    item["sales_org"]
                    for item in db.execute(
                        "SELECT sales_org FROM user_sales_org_admin WHERE user_id=? ORDER BY sales_org",
                        (row["id"],),
                    )
                ]
            else:
                admin_sales_org_access = []
    if not authenticated or row is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    expiry = int((utcnow() + timedelta(hours=10)).timestamp())
    cookie = sign_session(int(row["id"]), row["role"], expiry)
    response.set_cookie(
        "arba_session",
        cookie,
        httponly=True,
        samesite="lax",
        secure=os.getenv("ARBA_COOKIE_SECURE", "0") == "1",
        max_age=10 * 60 * 60,
    )
    return {
        "user": {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
            "admin_sales_org_access": admin_sales_org_access,
        }
    }


@app.post(f"{API_PREFIX}/auth/signup", status_code=201)
async def signup(payload: SignupPayload, response: Response) -> dict[str, Any]:
    email = payload.email.strip().lower()
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Name must contain at least 2 characters")
    hashed_password = password_hash(payload.password)
    with DB_LOCK, connect() as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM app_user WHERE email=? COLLATE NOCASE", (email,)
            ).fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists. Sign in or contact an administrator.",
                )
            first_user_admin = (
                db.execute("SELECT 1 FROM app_user WHERE is_seed=0 LIMIT 1").fetchone() is None
            )
            role = "ADMIN" if first_user_admin else "VIEWER"
            cursor = db.execute(
                "INSERT INTO app_user(email,name,role,password_hash,is_seed,last_login_at) "
                "VALUES(?,?,?,?,0,?)",
                (email, name, role, hashed_password, utcnow().isoformat()),
            )
            user_id = int(cursor.lastrowid)
            audit(
                db,
                "app_user",
                str(user_id),
                "SIGN_UP",
                email,
                after={"role": role},
            )
            row = db.execute(
                "SELECT id,email,name,role FROM app_user WHERE id=?", (user_id,)
            ).fetchone()
    set_session_cookie(response, int(row["id"]), str(row["role"]))
    return {"user": dict(row), "first_user_admin": first_user_admin}


def set_session_cookie(response: Response, user_id: int, role: str) -> None:
    expiry = int((utcnow() + timedelta(hours=10)).timestamp())
    response.set_cookie(
        "arba_session",
        sign_session(user_id, role, expiry),
        httponly=True,
        samesite="lax",
        secure=os.getenv("ARBA_COOKIE_SECURE", "0") == "1",
        max_age=10 * 60 * 60,
    )


@app.get(f"{API_PREFIX}/auth/sso/status")
async def sso_status() -> dict[str, Any]:
    return {"enabled": entra_sso_config() is not None, "provider": "Microsoft Entra ID"}


@app.get(f"{API_PREFIX}/auth/sso/start")
async def sso_start() -> Response:
    config = entra_sso_config()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="SSO is not configured. Set the ARBA_ENTRA_* environment variables.",
        )
    try:
        tenant_id = str(UUID(config["tenant_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="ARBA_ENTRA_TENANT_ID must be a tenant UUID") from exc
    redirect_uri = config["redirect_uri"]
    parsed_redirect_uri = urlsplit(redirect_uri)
    is_local_http = parsed_redirect_uri.scheme == "http" and parsed_redirect_uri.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if (
        parsed_redirect_uri.scheme != "https" and not is_local_http
    ) or not parsed_redirect_uri.netloc or parsed_redirect_uri.fragment or parsed_redirect_uri.username:
        raise HTTPException(
            status_code=500,
            detail="ARBA_ENTRA_REDIRECT_URI must use HTTPS (HTTP is allowed only for local development)",
        )

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    authorize_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
    query = urlencode(
        {
            "client_id": config["client_id"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": SSO_SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(f"{authorize_url}?{query}", status_code=302)
    response.set_cookie(
        SSO_STATE_COOKIE,
        signed_sso_state(state, verifier),
        httponly=True,
        samesite="lax",
        secure=os.getenv("ARBA_COOKIE_SECURE", "0") == "1",
        max_age=600,
        path=f"{API_PREFIX}/auth/sso",
    )
    return response


@app.get(f"{API_PREFIX}/auth/sso/callback")
async def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    response: Response
    if error:
        result = "cancelled" if error == "access_denied" else "failed"
        response = RedirectResponse(f"/?sso_error={result}", status_code=303)
        response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
        return response
    verifier = verify_sso_state(request.cookies.get(SSO_STATE_COOKIE), state or "")
    config = entra_sso_config()
    if not code or verifier is None or config is None:
        response = RedirectResponse("/?sso_error=invalid_state", status_code=303)
        response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
        return response
    try:
        tenant_id = str(UUID(config["tenant_id"]))
    except ValueError:
        response = RedirectResponse("/?sso_error=configuration", status_code=303)
        response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
        return response

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    try:
        tokens = await asyncio.to_thread(
            sso_http_json,
            token_url,
            {
                "grant_type": "authorization_code",
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": config["redirect_uri"],
                "code_verifier": verifier,
                "scope": SSO_SCOPES,
            },
        )
        access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise SSOAuthenticationError("The identity provider did not return an access token")
        profile = await asyncio.to_thread(
            sso_http_json,
            "https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName",
            None,
            access_token,
        )
        if not isinstance(profile, dict):
            raise SSOAuthenticationError("The identity provider returned an invalid profile")
    except SSOAuthenticationError:
        logger.warning("Microsoft Entra SSO authentication failed")
        response = RedirectResponse("/?sso_error=authentication_failed", status_code=303)
        response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
        return response

    subject = profile.get("id")
    email = str(profile.get("mail") or profile.get("userPrincipalName") or "").strip().lower()
    name = str(profile.get("displayName") or email.split("@", maxsplit=1)[0]).strip()
    if not isinstance(subject, str) or not subject or email.count("@") != 1 or not name:
        response = RedirectResponse("/?sso_error=profile_incomplete", status_code=303)
        response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
        return response
    sso_subject = f"entra:{tenant_id}:{subject}"

    with DB_LOCK, connect() as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id,email,name,role,active FROM app_user WHERE sso_subject=?",
                (sso_subject,),
            ).fetchone()
            created = row is None
            if row is None:
                email_row = db.execute(
                    "SELECT id FROM app_user WHERE email=? COLLATE NOCASE", (email,)
                ).fetchone()
                if email_row:
                    response = RedirectResponse("/?sso_error=account_exists", status_code=303)
                    response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
                    return response
                first_user_admin = (
                    db.execute("SELECT 1 FROM app_user WHERE is_seed=0 LIMIT 1").fetchone() is None
                )
                role = "ADMIN" if first_user_admin else "VIEWER"
                cursor = db.execute(
                    "INSERT INTO app_user(email,name,role,password_hash,sso_subject) "
                    "VALUES(?,?,?,?,?)",
                    (email, name, role, password_hash(secrets.token_urlsafe(32)), sso_subject),
                )
                user_id = int(cursor.lastrowid)
                row = db.execute(
                    "SELECT id,email,name,role,active FROM app_user WHERE id=?", (user_id,)
                ).fetchone()
                audit(db, "app_user", str(user_id), "SSO_SIGN_UP", email, after={"role": role})
            if row is None or not row["active"]:
                response = RedirectResponse("/?sso_error=account_inactive", status_code=303)
                response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
                return response
            db.execute(
                "UPDATE app_user SET last_login_at=? WHERE id=?",
                (utcnow().isoformat(), row["id"]),
            )
            row = db.execute(
                "SELECT id,email,name,role,active FROM app_user WHERE id=?", (row["id"],)
            ).fetchone()

    sso_result = (
        "created_admin" if created and first_user_admin else "created"
    ) if created else "signed_in"
    response = RedirectResponse(f"/?sso={sso_result}", status_code=303)
    set_session_cookie(response, int(row["id"]), str(row["role"]))
    response.delete_cookie(SSO_STATE_COOKIE, path=f"{API_PREFIX}/auth/sso")
    return response


@app.post(f"{API_PREFIX}/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie("arba_session", httponly=True, samesite="lax")
    return {"status": "signed out"}


@app.get(f"{API_PREFIX}/auth/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    return user


@app.get(f"{API_PREFIX}/bootstrap")
async def bootstrap(user: CurrentUser) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        if user["role"] == "ADMIN":
            market_query = (
                "SELECT code,name,plan_mode,p10_sales_org,horizon_weeks FROM market "
                "WHERE active=1 ORDER BY code"
            )
            customer_query = (
                "SELECT id,market_code,name FROM customer_l04 WHERE active=1 ORDER BY name"
            )
            listing_query = "SELECT market_code,customer_id,p09_code FROM listing"
            params: tuple[Any, ...] = ()
        else:
            admin_orgs = user.get("admin_sales_org_access", [])
            if admin_orgs:
                placeholders = ",".join("?" for _ in admin_orgs)
                market_query = (
                    "SELECT DISTINCT m.code,m.name,m.plan_mode,m.p10_sales_org,m.horizon_weeks "
                    "FROM market m LEFT JOIN user_sales_org so ON so.sales_org=m.p10_sales_org "
                    f"WHERE m.active=1 AND (m.p10_sales_org IN ({placeholders}) OR so.user_id=?) ORDER BY m.code"
                )
                customer_query = (
                    "SELECT DISTINCT c.id,c.market_code,c.name FROM customer_l04 c "
                    "JOIN market m ON m.code=c.market_code "
                    "LEFT JOIN user_assignment ua ON ua.market_code=c.market_code AND ua.customer_id=c.id "
                    f"WHERE c.active=1 AND (m.p10_sales_org IN ({placeholders}) OR ua.user_id=?) ORDER BY c.name"
                )
                listing_query = (
                    "SELECT l.market_code,l.customer_id,l.p09_code FROM listing l "
                    "JOIN market m ON m.code=l.market_code "
                    "LEFT JOIN user_assignment ua ON ua.market_code=l.market_code AND ua.customer_id=l.customer_id "
                    f"WHERE m.p10_sales_org IN ({placeholders}) OR ua.user_id=?"
                )
                params = (*admin_orgs, user["id"])
            else:
                market_query = (
                    "SELECT DISTINCT m.code,m.name,m.plan_mode,m.p10_sales_org,m.horizon_weeks "
                    "FROM market m JOIN user_sales_org so ON so.sales_org=m.p10_sales_org "
                    "WHERE m.active=1 AND so.user_id=? ORDER BY m.code"
                )
                customer_query = (
                    "SELECT DISTINCT c.id,c.market_code,c.name FROM customer_l04 c "
                    "JOIN user_assignment ua ON ua.market_code=c.market_code AND ua.customer_id=c.id "
                    "JOIN market m ON m.code=c.market_code "
                    "JOIN user_sales_org so ON so.user_id=ua.user_id AND so.sales_org=m.p10_sales_org "
                    "WHERE c.active=1 AND ua.user_id=? ORDER BY c.name"
                )
                listing_query = (
                    "SELECT DISTINCT l.market_code,l.customer_id,l.p09_code FROM listing l "
                    "JOIN user_assignment ua ON ua.market_code=l.market_code AND ua.customer_id=l.customer_id "
                    "WHERE ua.user_id=?"
                )
                params = (user["id"],)
        markets = [
            dict(r)
            for r in db.execute(market_query, params)
        ]
        customers = [
            dict(r)
            for r in db.execute(customer_query, params)
        ]
        products = [
            dict(r)
            for r in db.execute(
                "SELECT code,description,brand,sub_brand,category FROM product_p09 WHERE active=1 ORDER BY brand,description"
            )
        ]
        tactics = [
            dict(r)
            for r in db.execute("SELECT market_code,name FROM tactic WHERE active=1 ORDER BY name")
        ]
        listing_rows = [
            dict(r) for r in db.execute(listing_query, params)
        ]
    return {
        "user": user,
        "markets": markets,
        "customers": customers,
        "products": products,
        "tactics": tactics,
        "listings": listing_rows,
        "weeks": future_weeks(),
        "history_weeks": historical_weeks(),
    }


def product_rows_for_account(
    db: sqlite3.Connection, market: str, customer_id: int, include_approved: bool = True
) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT DISTINCT p.code,p.description,p.brand,p.sub_brand,p.category
        FROM product_p09 p
        WHERE p.active=1 AND (
          EXISTS(SELECT 1 FROM listing l WHERE l.market_code=? AND l.customer_id=? AND l.p09_code=p.code)
          OR (?=1 AND EXISTS(
            SELECT 1 FROM promotion pr JOIN promotion_item pi ON pi.promotion_id=pr.id
            WHERE pr.market_code=? AND pr.customer_id=? AND pr.status='APPROVED' AND pi.p09_code=p.code
          ))
        )
        ORDER BY p.brand,p.description
        """,
        (market, customer_id, int(include_approved), market, customer_id),
    ).fetchall()


@app.get(f"{API_PREFIX}/baseline")
async def get_baseline(market: str, customer_id: int, user: CurrentUser) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        market_row = db.execute(
            "SELECT plan_mode,horizon_weeks FROM market WHERE code=?", (market,)
        ).fetchone()
        if market_row is None:
            raise HTTPException(status_code=404, detail="Market not found")
        rows = product_rows_for_account(db, market, customer_id, include_approved=False)
        weeks = future_weeks(int(market_row["horizon_weeks"]))
        result = []
        for product in rows:
            baseline = {
                r["iso_week"]: r["qty_cs"]
                for r in db.execute(
                    "SELECT iso_week,qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            actual = {
                r["iso_week"]: r["qty_cs"]
                for r in db.execute(
                    "SELECT iso_week,qty_cs FROM actual_sellin WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            result.append(
                {
                    **dict(product),
                    "baseline": [baseline.get(w, 0) for w in weeks],
                    "actual_last_year": [
                        actual.get(iso_week(week_monday(w) - timedelta(weeks=52)), 0) for w in weeks
                    ],
                }
            )
    return {
        "market": market,
        "customer_id": customer_id,
        "plan_mode": market_row["plan_mode"],
        "weeks": weeks,
        "products": result,
    }


@app.put(f"{API_PREFIX}/baseline")
async def save_baseline(payload: BaselineSave, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "PLANNER")
    if not payload.cells:
        return {"saved": 0}
    with DB_LOCK, connect() as db:
        with db:
            market_row = db.execute(
                "SELECT plan_mode,horizon_weeks FROM market WHERE code=?",
                (payload.market,),
            ).fetchone()
            if market_row is None:
                raise HTTPException(status_code=404, detail="Market not found")
            check_assignment(db, user, payload.market, payload.customer_id)
            weeks = set(future_weeks(int(market_row["horizon_weeks"])))
            listed = {
                row["p09_code"]
                for row in db.execute(
                    "SELECT p09_code FROM listing WHERE market_code=? AND customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            unique: set[tuple[str, str]] = set()
            values = []
            for cell in payload.cells:
                if not math.isfinite(cell.qty_cs):
                    raise HTTPException(
                        status_code=422, detail="Baseline values must be finite numbers"
                    )
                try:
                    week_monday(cell.week)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if cell.week not in weeks:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Past or out-of-horizon week is locked: {cell.week}",
                    )
                if cell.product not in listed:
                    raise HTTPException(
                        status_code=400, detail=f"Product is not listed: {cell.product}"
                    )
                key = (cell.product, cell.week)
                if key in unique:
                    raise HTTPException(
                        status_code=422,
                        detail="Duplicate product/week cells in request",
                    )
                unique.add(key)
                values.append(
                    (
                        payload.market,
                        payload.customer_id,
                        cell.product,
                        cell.week,
                        cell.qty_cs,
                        "MANUAL",
                        user["email"],
                        utcnow().isoformat(),
                    )
                )
            db.executemany(
                "INSERT INTO baseline(market_code,customer_id,p09_code,iso_week,qty_cs,source,changed_by,changed_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(market_code,customer_id,p09_code,iso_week) "
                "DO UPDATE SET qty_cs=excluded.qty_cs,source=excluded.source,changed_by=excluded.changed_by,changed_at=excluded.changed_at",
                values,
            )
            audit(
                db,
                "baseline",
                f"{payload.market}:{payload.customer_id}",
                "BULK_UPSERT",
                user["email"],
                after={"cells": len(values)},
            )
    return {"saved": len(values)}


@app.get(f"{API_PREFIX}/baseline/export")
async def export_baseline(market: str, customer_id: int, user: CurrentUser) -> Response:
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        market_row = db.execute(
            "SELECT plan_mode,horizon_weeks FROM market WHERE code=?", (market,)
        ).fetchone()
        if market_row is None:
            raise HTTPException(status_code=404, detail="Market not found")
        customer = db.execute(
            "SELECT id,external_code FROM customer_l04 WHERE market_code=? AND id=? AND active=1",
            (market, customer_id),
        ).fetchone()
        if customer is None:
            raise HTTPException(status_code=404, detail="Plan account not found")
        customer_code = customer["external_code"] or str(customer["id"])
        weeks = future_weeks(int(market_row["horizon_weeks"]))
        products = product_rows_for_account(db, market, customer_id, include_approved=False)
        rows = []
        for product in products:
            baseline_by_week = {
                row["iso_week"]: float(row["qty_cs"])
                for row in db.execute(
                    "SELECT iso_week,qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            rows.extend(
                {
                    "Customer ID": str(customer_code),
                    "Product P09": product["code"],
                    "Week": week,
                    "Baseline Cases": str(baseline_by_week.get(week, 0)),
                }
                for week in weeks
            )
    columns = ("Customer ID", "Product P09", "Week", "Baseline Cases")
    filename = f"baseline_{market}_{customer_id}.xlsx"
    return Response(
        build_xlsx(rows, columns),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post(f"{API_PREFIX}/baseline/upload")
async def upload_baseline(payload: BaselineFileUpload, user: CurrentUser) -> dict[str, int]:
    require_role(user, "PLANNER")
    if Path(payload.filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=415, detail="Upload a baseline XLSX workbook")
    try:
        contents = base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The upload is not valid base64 data") from exc
    if not contents or len(contents) > 10_000_000:
        raise HTTPException(status_code=413, detail="Baseline workbook must be between 1 byte and 10 MB")
    try:
        rows = master_file_rows(payload.filename, contents)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not rows or len(rows) > 20_000:
        raise HTTPException(status_code=422, detail="Baseline workbook must contain between 1 and 20,000 data rows")

    with DB_LOCK, connect() as db:
        with db:
            market_row = db.execute(
                "SELECT plan_mode,horizon_weeks FROM market WHERE code=?", (payload.market,)
            ).fetchone()
            if market_row is None:
                raise HTTPException(status_code=404, detail="Market not found")
            check_assignment(db, user, payload.market, payload.customer_id)
            customer = db.execute(
                "SELECT id,external_code FROM customer_l04 WHERE market_code=? AND id=? AND active=1",
                (payload.market, payload.customer_id),
            ).fetchone()
            if customer is None:
                raise HTTPException(status_code=404, detail="Plan account not found")
            allowed_customer_ids = {str(customer["id"])}
            if customer["external_code"]:
                allowed_customer_ids.add(str(customer["external_code"]))
            weeks = set(future_weeks(int(market_row["horizon_weeks"])))
            listed = {
                row["p09_code"]
                for row in db.execute(
                    "SELECT p09_code FROM listing WHERE market_code=? AND customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            unique: set[tuple[str, str]] = set()
            values = []
            for row_number, row in rows:
                customer_id_value = required_master_value(row, "Customer ID", "Customer L04")
                product = required_master_value(row, "Product P09", "P09", "Product")
                week = required_master_value(row, "Week", "ISO Week")
                quantity_text = required_master_value(row, "Baseline Cases", "Baseline")
                if customer_id_value not in allowed_customer_ids:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Row {row_number}: Customer ID does not match the selected plan account",
                    )
                if product not in listed:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Row {row_number}: P09 product is not listed for this plan account ({product})",
                    )
                try:
                    week_monday(week)
                    quantity = float(quantity_text)
                except (ValueError, OverflowError) as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Row {row_number}: Week or Baseline Cases is invalid",
                    ) from exc
                if week not in weeks:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Row {row_number}: Past or out-of-horizon week is locked ({week})",
                    )
                if not math.isfinite(quantity) or quantity < 0:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Row {row_number}: Baseline Cases must be a non-negative number",
                    )
                key = (product, week)
                if key in unique:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Row {row_number}: Duplicate P09 product and week",
                    )
                unique.add(key)
                values.append(
                    (
                        payload.market,
                        payload.customer_id,
                        product,
                        week,
                        quantity,
                        "UPLOAD",
                        user["email"],
                        utcnow().isoformat(),
                    )
                )
            db.executemany(
                "INSERT INTO baseline(market_code,customer_id,p09_code,iso_week,qty_cs,source,changed_by,changed_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(market_code,customer_id,p09_code,iso_week) "
                "DO UPDATE SET qty_cs=excluded.qty_cs,source=excluded.source,"
                "changed_by=excluded.changed_by,changed_at=excluded.changed_at",
                values,
            )
            audit(
                db,
                "baseline",
                f"{payload.market}:{payload.customer_id}",
                "UPLOAD",
                user["email"],
                after={"cells": len(values), "filename": Path(payload.filename).name},
            )
    return {"saved": len(values)}


def promotion_baseline(
    db: sqlite3.Connection,
    market: str,
    customer_id: int,
    product: str,
    start: date,
    end: date,
) -> float:
    cursor = start - timedelta(days=start.weekday())
    final = end - timedelta(days=end.weekday())
    total = 0.0
    while cursor <= final:
        week = iso_week(cursor)
        row = db.execute(
            "SELECT qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
            (market, customer_id, product, week),
        ).fetchone()
        total += float(row["qty_cs"]) if row else 0.0
        cursor += timedelta(weeks=1)
    return total


def promotion_json(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    items = []
    for item in db.execute(
        "SELECT pi.p09_code,pi.total_cs,p.description FROM promotion_item pi "
        "JOIN product_p09 p ON p.code=pi.p09_code WHERE pi.promotion_id=? ORDER BY p.description",
        (row["id"],),
    ):
        baseline = promotion_baseline(
            db,
            row["market_code"],
            row["customer_id"],
            item["p09_code"],
            date.fromisoformat(row["start_date"]),
            date.fromisoformat(row["end_date"]),
        )
        total = float(item["total_cs"])
        actual = 0.0
        if date.fromisoformat(row["end_date"]) < date.today():
            actual = float(
                db.execute(
                    "SELECT COALESCE(SUM(qty_cs),0) AS q FROM actual_sellin "
                    "WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week BETWEEN ? AND ?",
                    (
                        row["market_code"],
                        row["customer_id"],
                        item["p09_code"],
                        iso_week(date.fromisoformat(row["start_date"])),
                        iso_week(date.fromisoformat(row["end_date"])),
                    ),
                ).fetchone()["q"]
            )
        items.append(
            {
                "product": item["p09_code"],
                "description": item["description"],
                "baseline": baseline,
                "total": total,
                "uplift": total - baseline,
                "actual": actual,
            }
        )
    return {
        **dict(row),
        "items": items,
        "baseline": sum(i["baseline"] for i in items),
        "total": sum(i["total"] for i in items),
        "uplift": sum(i["uplift"] for i in items),
        "actual": sum(i["actual"] for i in items),
    }


@app.get(f"{API_PREFIX}/promotions/baseline")
async def promotion_baselines(
    market: str,
    customer_id: int,
    start_date: date,
    end_date: date,
    user: CurrentUser,
) -> dict[str, Any]:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="End Date must be on or after Start Date")
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        rows = db.execute(
            "SELECT p.code FROM listing l JOIN product_p09 p ON p.code=l.p09_code "
            "WHERE l.market_code=? AND l.customer_id=? AND p.active=1 ORDER BY p.description",
            (market, customer_id),
        ).fetchall()
        baselines = {
            row["code"]: promotion_baseline(
                db, market, customer_id, row["code"], start_date, end_date
            )
            for row in rows
        }
    return {"baselines": baselines}


@app.get(f"{API_PREFIX}/promotions")
async def get_promotions(
    user: CurrentUser, market: str | None = None, customer_id: int | None = None
) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        query = "SELECT pr.*,c.name AS customer_name FROM promotion pr JOIN customer_l04 c ON c.id=pr.customer_id WHERE 1=1"
        parameters: list[Any] = []
        if market:
            query += " AND pr.market_code=?"
            parameters.append(market)
        if customer_id:
            query += " AND pr.customer_id=?"
            parameters.append(customer_id)
        if user["role"] != "ADMIN":
            query += " AND EXISTS(SELECT 1 FROM user_assignment ua WHERE ua.user_id=? AND ua.market_code=pr.market_code AND ua.customer_id=pr.customer_id)"
            parameters.append(user["id"])
        rows = db.execute(
            query + " ORDER BY pr.start_date DESC,pr.promo_number DESC", parameters
        ).fetchall()
        promos = [promotion_json(db, row) for row in rows]
    return {"promotions": promos}


def next_promo_number(db: sqlite3.Connection) -> str:
    row = db.execute(
        "SELECT MAX(CAST(SUBSTR(promo_number,3) AS INTEGER)) AS n FROM promotion"
    ).fetchone()
    return f"PR{(int(row['n'] or 0) + 1):06d}"


@app.post(f"{API_PREFIX}/promotions")
async def save_promotion(payload: PromoPayload, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "PLANNER", "APPROVER")
    if payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=422, detail="Promotion End Date must be on or after Start Date"
        )
    if payload.cons_end < payload.cons_start:
        raise HTTPException(
            status_code=422,
            detail="Consumption End must be on or after Consumption Start",
        )
    if not payload.items:
        raise HTTPException(status_code=422, detail="Select at least one promotion product")
    with DB_LOCK, connect() as db:
        with db:
            market = db.execute(
                "SELECT plan_mode FROM market WHERE code=?", (payload.market,)
            ).fetchone()
            if market is None:
                raise HTTPException(status_code=404, detail="Market not found")
            check_assignment(db, user, payload.market, payload.customer_id)
            tactic = db.execute(
                "SELECT 1 FROM tactic WHERE market_code=? AND name=? AND active=1",
                (payload.market, payload.tactic),
            ).fetchone()
            if not tactic:
                raise HTTPException(
                    status_code=422, detail="Tactic is not configured for this market"
                )
            listed = {
                r["p09_code"]
                for r in db.execute(
                    "SELECT p09_code FROM listing WHERE market_code=? AND customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            if not set(payload.items).issubset(listed):
                raise HTTPException(
                    status_code=400,
                    detail="Every promotion product must be listed for this account",
                )
            for product, total in payload.items.items():
                if not math.isfinite(total) or total < 0:
                    raise HTTPException(status_code=422, detail="Item totals must be non-negative")
                baseline = promotion_baseline(
                    db,
                    payload.market,
                    payload.customer_id,
                    product,
                    payload.start_date,
                    payload.end_date,
                )
                if total < baseline:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Total cases for {product} must be at least its baseline ({baseline:g})",
                    )

            if payload.id is None:
                promo_number = next_promo_number(db)
                cursor = db.execute(
                    "INSERT INTO promotion(promo_number,market_code,customer_id,start_date,end_date,cons_start,cons_end,"
                    "tactic,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        promo_number,
                        payload.market,
                        payload.customer_id,
                        payload.start_date.isoformat(),
                        payload.end_date.isoformat(),
                        payload.cons_start.isoformat(),
                        payload.cons_end.isoformat(),
                        payload.tactic,
                        "NEW",
                        user["email"],
                        utcnow().isoformat(),
                    ),
                )
                promo_id = int(cursor.lastrowid)
                log_status(db, promo_id, user["email"], None, "NEW")
                old_status = "NEW"
            else:
                row = db.execute("SELECT * FROM promotion WHERE id=?", (payload.id,)).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="Promotion not found")
                check_assignment(db, user, row["market_code"], int(row["customer_id"]))
                if row["status"] not in {"NEW", "SAVED"}:
                    raise HTTPException(
                        status_code=409,
                        detail="Only Entry or Planned promotions can be edited; revert an approved promotion first.",
                    )
                if payload.version is None or payload.version != row["version"]:
                    raise HTTPException(
                        status_code=409,
                        detail="Promotion was changed by another user. Reload before saving.",
                    )
                promo_id = int(row["id"])
                old_status = row["status"]
                cursor = db.execute(
                    "UPDATE promotion SET market_code=?,customer_id=?,start_date=?,end_date=?,cons_start=?,cons_end=?,"
                    "tactic=?,version=version+1 WHERE id=? AND version=?",
                    (
                        payload.market,
                        payload.customer_id,
                        payload.start_date.isoformat(),
                        payload.end_date.isoformat(),
                        payload.cons_start.isoformat(),
                        payload.cons_end.isoformat(),
                        payload.tactic,
                        promo_id,
                        row["version"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise HTTPException(
                        status_code=409, detail="Promotion was changed by another user"
                    )
            warnings = db.execute(
                "SELECT DISTINCT pr.promo_number FROM promotion pr JOIN promotion_item pi ON pi.promotion_id=pr.id "
                "WHERE pr.market_code=? AND pr.customer_id=? AND pr.id<>? "
                "AND pr.start_date<=? AND pr.end_date>=? AND pi.p09_code IN ({})".format(
                    ",".join("?" for _ in payload.items)
                ),
                (
                    payload.market,
                    payload.customer_id,
                    promo_id,
                    payload.end_date.isoformat(),
                    payload.start_date.isoformat(),
                    *payload.items.keys(),
                ),
            ).fetchall()
            db.execute("DELETE FROM promotion_item WHERE promotion_id=?", (promo_id,))
            db.executemany(
                "INSERT INTO promotion_item(promotion_id,p09_code,total_cs) VALUES(?,?,?)",
                [(promo_id, product, total) for product, total in payload.items.items()],
            )
            audit(
                db,
                "promotion",
                str(promo_id),
                "CREATE_ENTRY" if payload.id is None else "EDIT",
                user["email"],
                before={"status": old_status},
                after={
                    "status": "NEW" if payload.id is None else old_status,
                    "products": list(payload.items),
                },
            )
            result = promotion_json(
                db,
                db.execute("SELECT * FROM promotion WHERE id=?", (promo_id,)).fetchone(),
            )
    return {
        "promotion": result,
        "overlap_warnings": [r["promo_number"] for r in warnings],
    }


@app.post(f"{API_PREFIX}/promotions/{{promotion_id}}/save")
async def plan_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "PLANNER", "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "NEW":
                raise HTTPException(status_code=409, detail="Only Entry promotions can be saved as Planned")
            db.execute(
                "UPDATE promotion SET status='SAVED',version=version+1 WHERE id=? AND status='NEW'",
                (promotion_id,),
            )
            log_status(db, promotion_id, user["email"], "NEW", "SAVED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "SAVE",
                user["email"],
                before={"status": "NEW"},
                after={"status": "SAVED"},
            )
    return {"status": "SAVED"}


@app.post(f"{API_PREFIX}/promotions/{{promotion_id}}/confirm")
async def confirm_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "PLANNER", "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "SAVED":
                raise HTTPException(status_code=409, detail="Only Planned promotions can be confirmed")
            db.execute(
                "UPDATE promotion SET status='CHANGED',version=version+1 WHERE id=? AND status='SAVED'",
                (promotion_id,),
            )
            log_status(db, promotion_id, user["email"], "SAVED", "CHANGED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "CONFIRM",
                user["email"],
                before={"status": "SAVED"},
                after={"status": "CHANGED"},
            )
    return {"status": "CHANGED"}


@app.post(f"{API_PREFIX}/promotions/{{promotion_id}}/approve")
async def approve_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "CHANGED":
                raise HTTPException(status_code=409, detail="Only Approval Pending promotions can be approved")
            db.execute(
                "UPDATE promotion SET status='APPROVED',approved_by=?,approved_at=?,version=version+1 "
                "WHERE id=? AND status='CHANGED'",
                (user["email"], utcnow().isoformat(), promotion_id),
            )
            log_status(db, promotion_id, user["email"], "CHANGED", "APPROVED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "APPROVE",
                user["email"],
                before={"status": "CHANGED"},
                after={"status": "APPROVED"},
            )
    return {"status": "APPROVED"}


@app.post(f"{API_PREFIX}/promotions/{{promotion_id}}/revert")
async def revert_promotion(promotion_id: int, user: CurrentUser) -> dict[str, str]:
    require_role(user, "PLANNER", "APPROVER")
    with DB_LOCK, connect() as db:
        with db:
            row = db.execute("SELECT * FROM promotion WHERE id=?", (promotion_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Promotion not found")
            check_assignment(db, user, row["market_code"], row["customer_id"])
            if row["status"] != "APPROVED" or date.fromisoformat(row["start_date"]) <= date.today():
                raise HTTPException(
                    status_code=409,
                    detail="Only future APPROVED promotions can be reverted",
                )
            db.execute(
                "UPDATE promotion SET status='SAVED',approved_by=NULL,approved_at=NULL,version=version+1 WHERE id=?",
                (promotion_id,),
            )
            log_status(db, promotion_id, user["email"], "APPROVED", "SAVED")
            audit(
                db,
                "promotion",
                str(promotion_id),
                "REVERT",
                user["email"],
                before={"status": "APPROVED"},
                after={"status": "SAVED"},
            )
    return {"status": "SAVED"}


@app.get(f"{API_PREFIX}/listing")
async def get_listing(market: str, customer_id: int, user: CurrentUser) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        selected = [
            r["p09_code"]
            for r in db.execute(
                "SELECT p09_code FROM listing WHERE market_code=? AND customer_id=?",
                (market, customer_id),
            )
        ]
        products = [
            dict(r)
            for r in db.execute(
                "SELECT code,description,brand,sub_brand,category FROM product_p09 ORDER BY brand,description"
            )
        ]
    return {"selected": selected, "products": products}


@app.put(f"{API_PREFIX}/listing")
async def save_listing(payload: ListingPayload, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "PLANNER")
    with DB_LOCK, connect() as db:
        with db:
            check_assignment(db, user, payload.market, payload.customer_id)
            valid = {r["code"] for r in db.execute("SELECT code FROM product_p09 WHERE active=1")}
            if not set(payload.products).issubset(valid):
                raise HTTPException(status_code=422, detail="Unknown product in listing")
            current = {
                r["p09_code"]
                for r in db.execute(
                    "SELECT p09_code FROM listing WHERE market_code=? AND customer_id=?",
                    (payload.market, payload.customer_id),
                )
            }
            removed = current - set(payload.products)
            warnings = []
            for product in removed:
                future_base = db.execute(
                    "SELECT 1 FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week>=? LIMIT 1",
                    (
                        payload.market,
                        payload.customer_id,
                        product,
                        iso_week(date.today()),
                    ),
                ).fetchone()
                approved = db.execute(
                    "SELECT 1 FROM promotion_item pi JOIN promotion pr ON pr.id=pi.promotion_id WHERE pr.market_code=? AND pr.customer_id=? AND pi.p09_code=? AND pr.status='APPROVED' AND pr.start_date>? LIMIT 1",
                    (
                        payload.market,
                        payload.customer_id,
                        product,
                        date.today().isoformat(),
                    ),
                ).fetchone()
                if future_base or approved:
                    warnings.append(product)
            db.execute(
                "DELETE FROM listing WHERE market_code=? AND customer_id=?",
                (payload.market, payload.customer_id),
            )
            db.executemany(
                "INSERT INTO listing(market_code,customer_id,p09_code,created_by,created_at) VALUES(?,?,?,?,?)",
                [
                    (
                        payload.market,
                        payload.customer_id,
                        p,
                        user["email"],
                        utcnow().isoformat(),
                    )
                    for p in payload.products
                ],
            )
            audit(
                db,
                "listing",
                f"{payload.market}:{payload.customer_id}",
                "REPLACE",
                user["email"],
                before=sorted(current),
                after=sorted(payload.products),
            )
    return {"saved": len(payload.products), "delisted_with_plans": warnings}


@app.get(f"{API_PREFIX}/history")
async def sales_history(market: str, customer_id: int, user: CurrentUser) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        products = product_rows_for_account(db, market, customer_id, include_approved=False)
        weeks = historical_weeks()
        result = []
        for product in products:
            lookup = {
                r["iso_week"]: r["qty_cs"]
                for r in db.execute(
                    "SELECT iso_week,qty_cs FROM actual_sellin WHERE market_code=? AND customer_id=? AND p09_code=?",
                    (market, customer_id, product["code"]),
                )
            }
            result.append({**dict(product), "values": [lookup.get(w, 0) for w in weeks]})
    return {"weeks": weeks, "products": result}


def approved_uplift(
    db: sqlite3.Connection, market: str, customer: int, product: str, week: str
) -> float:
    monday = week_monday(week)
    sunday = monday + timedelta(days=6)
    total = 0.0
    rows = db.execute(
        "SELECT pr.start_date,pr.end_date,pi.total_cs FROM promotion pr "
        "JOIN promotion_item pi ON pi.promotion_id=pr.id "
        "WHERE pr.market_code=? AND pr.customer_id=? AND pr.status='APPROVED' AND pi.p09_code=? "
        "AND pr.start_date<=? AND pr.end_date>=?",
        (market, customer, product, sunday.isoformat(), monday.isoformat()),
    )
    for row in rows:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        weeks = max(
            1,
            ((end - timedelta(days=end.weekday())) - (start - timedelta(days=start.weekday()))).days
            // 7
            + 1,
        )
        base = promotion_baseline(db, market, customer, product, start, end)
        total += max(0.0, float(row["total_cs"]) - base) / weeks
    return total


def largest_remainder(total: int, shares: list[tuple[str, float]]) -> dict[str, int]:
    if not shares:
        return {}
    exact = [(material, total * share / 100) for material, share in shares]
    allocated = {material: int(value) for material, value in exact}
    remainder = total - sum(allocated.values())
    order = sorted(exact, key=lambda pair: pair[1] - int(pair[1]), reverse=True)
    for index in range(remainder):
        allocated[order[index % len(order)][0]] += 1
    return allocated


def build_p10_rows(db: sqlite3.Connection, market_code: str) -> list[dict[str, str]]:
    market = db.execute("SELECT * FROM market WHERE code=?", (market_code,)).fetchone()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    result = []
    weeks = future_weeks(int(market["horizon_weeks"]))
    customers = db.execute(
        "SELECT id,name FROM customer_l04 WHERE market_code=? AND active=1",
        (market_code,),
    )
    for customer in customers:
        products = product_rows_for_account(db, market_code, customer["id"], include_approved=True)
        for product in products:
            for week in weeks:
                base_row = db.execute(
                    "SELECT qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
                    (market_code, customer["id"], product["code"], week),
                ).fetchone()
                base_p09 = math.floor(float(base_row["qty_cs"]) + 0.5) if base_row else 0
                lift_p09 = math.floor(
                    approved_uplift(db, market_code, customer["id"], product["code"], week) + 0.5
                )
                split_rows = db.execute(
                    "SELECT s.material,s.share FROM p09_p10_split s "
                    "JOIN material_p10 m ON m.material=s.material WHERE s.p09_code=? AND m.active=1 "
                    "AND s.valid_from<=? ORDER BY s.valid_from DESC",
                    (product["code"], date.today().isoformat()),
                ).fetchall()
                latest: dict[str, float] = {}
                for split in split_rows:
                    latest.setdefault(split["material"], float(split["share"]))
                shares = list(latest.items())
                if not shares:
                    materials = [
                        r["material"]
                        for r in db.execute(
                            "SELECT material FROM material_p10 WHERE p09_code=? AND active=1",
                            (product["code"],),
                        )
                    ]
                    shares = [(m, 100 / len(materials)) for m in materials] if materials else []
                share_total = sum(share for _, share in shares)
                if shares and abs(share_total - 100) > 0.01:
                    raise HTTPException(
                        status_code=500,
                        detail=f"P10 split shares for {product['code']} sum to {share_total:.2f}%, not 100%",
                    )
                base_split = largest_remainder(base_p09, shares)
                lift_split = largest_remainder(lift_p09, shares)
                monday = week_monday(week)
                sunday = monday + timedelta(days=6)
                for material, _ in shares:
                    base = base_split[material]
                    lift = lift_split[material]
                    result.append(
                        {
                            "Start Date": f"{monday.isoformat()} 00:00:00",
                            "End Date": f"{sunday.isoformat()} 00:00:00",
                            "Plan Account": customer["name"],
                            "Material Number": material,
                            "BaseVolume": str(base),
                            "LiftVolume": str(lift),
                            "TotalVolume": str(base + lift),
                            "PromoNumber": f"00{customer['name']}{material}{monday:%Y%m%d}",
                            "Consumption Start": f"{monday.isoformat()} 00:00:00",
                            "Consumption End": f"{sunday.isoformat()} 00:00:00",
                            "Sales Org": market["p10_sales_org"],
                        }
                    )
    return result


P10_COLUMNS = (
    "Start Date",
    "End Date",
    "Plan Account",
    "Material Number",
    "BaseVolume",
    "LiftVolume",
    "TotalVolume",
    "PromoNumber",
    "Consumption Start",
    "Consumption End",
    "Sales Org",
)


def xlsx_column(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def build_xlsx(
    rows: list[dict[str, str]], columns: tuple[str, ...] = P10_COLUMNS
) -> bytes:
    spreadsheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    office_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ET.register_namespace("", spreadsheet_ns)
    ET.register_namespace("r", office_rel_ns)
    worksheet = ET.Element(f"{{{spreadsheet_ns}}}worksheet")
    sheet_data = ET.SubElement(worksheet, f"{{{spreadsheet_ns}}}sheetData")
    records = [list(columns), *[[row[column] for column in columns] for row in rows]]
    for row_number, values in enumerate(records, start=1):
        xml_row = ET.SubElement(sheet_data, f"{{{spreadsheet_ns}}}row", {"r": str(row_number)})
        for column_number, value in enumerate(values, start=1):
            cell = ET.SubElement(
                xml_row,
                f"{{{spreadsheet_ns}}}c",
                {"r": f"{xlsx_column(column_number)}{row_number}", "t": "inlineStr"},
            )
            inline = ET.SubElement(cell, f"{{{spreadsheet_ns}}}is")
            text = ET.SubElement(inline, f"{{{spreadsheet_ns}}}t")
            text.text = str(value)

    workbook = ET.Element(f"{{{spreadsheet_ns}}}workbook")
    sheets = ET.SubElement(workbook, f"{{{spreadsheet_ns}}}sheets")
    ET.SubElement(
        sheets,
        f"{{{spreadsheet_ns}}}sheet",
        {
            "name": "Sheet1",
            "sheetId": "1",
            f"{{{office_rel_ns}}}id": "rId1",
        },
    )

    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": ET.tostring(workbook, encoding="unicode", xml_declaration=True),
        "xl/worksheets/sheet1.xml": ET.tostring(
            worksheet, encoding="unicode", xml_declaration=True
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def store_outbound_file(filename: str, category: str, contents: bytes, user_email: str) -> None:
    OUTBOUND_DIR.mkdir(parents=True, exist_ok=True)
    stored = OUTBOUND_DIR / f"{secrets.token_hex(8)}_{Path(filename).name}"
    stored.write_bytes(contents)
    try:
        with DB_LOCK, connect() as db:
            with db:
                cursor = db.execute(
                    "INSERT INTO managed_file(direction,category,original_name,stored_path,status,uploaded_by,created_at,row_count,message) "
                    "VALUES('OUTBOUND',?,?,?,'EXPORTED',?,?,0,'P10 export')",
                    (category, filename, str(stored), user_email, utcnow().isoformat()),
                )
                audit(db, "managed_file", str(cursor.lastrowid), "EXPORT", user_email,
                      after={"category": category, "filename": filename})
    except sqlite3.Error:
        stored.unlink(missing_ok=True)
        raise


@app.get(f"{API_PREFIX}/report")
async def volume_report(
    user: CurrentUser, market: str, year: int, customer_id: int | None = None
) -> dict[str, Any]:
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=422, detail="Year must be between 2000 and 2100")
    with DB_LOCK, connect() as db:
        market_row = db.execute("SELECT plan_mode FROM market WHERE code=?", (market,)).fetchone()
        if not market_row:
            raise HTTPException(status_code=404, detail="Market not found")
        if customer_id:
            check_assignment(db, user, market, customer_id)
        else:
            assigned = {
                r["customer_id"]
                for r in db.execute(
                    "SELECT customer_id FROM user_assignment WHERE user_id=? AND market_code=?",
                    (user["id"], market),
                )
            }
            if user["role"] != "ADMIN" and not assigned:
                raise HTTPException(status_code=403, detail="Market is not assigned")
        params: list[Any] = [market]
        query = "SELECT id,name FROM customer_l04 WHERE market_code=? AND active=1"
        if customer_id:
            query += " AND id=?"
            params.append(customer_id)
        elif user["role"] != "ADMIN":
            marks = ",".join("?" for _ in assigned)
            query += f" AND id IN ({marks})"
            params.extend(sorted(assigned))
        customers = db.execute(query, params).fetchall()
        results = []
        for customer in customers:
            products = product_rows_for_account(db, market, customer["id"], include_approved=True)
            for product in products:
                months = [0.0] * 12
                for week in future_weeks(52) + historical_weeks(52):
                    monday = week_monday(week)
                    thursday = monday + timedelta(days=3)
                    if thursday.year != year:
                        continue
                    actual = db.execute(
                        "SELECT qty_cs FROM actual_sellin WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
                        (market, customer["id"], product["code"], week),
                    ).fetchone()
                    if monday < date.today() - timedelta(days=date.today().weekday()):
                        qty = float(actual["qty_cs"]) if actual else 0
                    else:
                        base = db.execute(
                            "SELECT qty_cs FROM baseline WHERE market_code=? AND customer_id=? AND p09_code=? AND iso_week=?",
                            (market, customer["id"], product["code"], week),
                        ).fetchone()
                        qty = float(base["qty_cs"]) if base else 0
                        if market_row["plan_mode"] == "PROMO":
                            qty += approved_uplift(
                                db, market, customer["id"], product["code"], week
                            )
                    months[thursday.month - 1] += qty
                results.append(
                    {
                        "customer": customer["name"],
                        "customer_id": customer["id"],
                        "product": product["code"],
                        "description": product["description"],
                        "brand": product["brand"],
                        "months": months,
                        "total": sum(months),
                    }
                )
    return {
        "year": year,
        "market": market,
        "rows": results,
        "month_names": [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
    }


@app.get(f"{API_PREFIX}/calendar")
async def promo_calendar(market: str, customer_id: int, user: CurrentUser) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        check_assignment(db, user, market, customer_id)
        market_row = db.execute(
            "SELECT horizon_weeks FROM market WHERE code=? AND active=1", (market,)
        ).fetchone()
        if market_row is None:
            raise HTTPException(status_code=404, detail="Market not found")
        rows = db.execute(
            "SELECT pr.id,pr.promo_number,pr.start_date,pr.end_date,pr.tactic,pr.status,"
            "c.name AS customer_name,p.sub_brand,COUNT(DISTINCT pi.p09_code) AS product_count "
            "FROM promotion pr JOIN promotion_item pi ON pi.promotion_id=pr.id "
            "JOIN product_p09 p ON p.code=pi.p09_code "
            "JOIN customer_l04 c ON c.id=pr.customer_id "
            "WHERE pr.market_code=? AND pr.customer_id=? AND pr.status IN ('SAVED','CHANGED','APPROVED') "
            "GROUP BY pr.id,p.sub_brand "
            "ORDER BY pr.start_date,pr.promo_number,p.sub_brand",
            (market, customer_id),
        ).fetchall()
        promotions = [dict(row) for row in rows]
        weeks = future_weeks(int(market_row["horizon_weeks"]))
    first_week = week_monday(weeks[0])
    last_week = week_monday(weeks[-1])
    if promotions:
        first_week = min(
            first_week,
            min(week_monday(iso_week(date.fromisoformat(row["start_date"]))) for row in promotions),
        )
        last_week = max(
            last_week,
            max(week_monday(iso_week(date.fromisoformat(row["end_date"]))) for row in promotions),
        )
    calendar_weeks = []
    week = first_week
    while week <= last_week:
        calendar_weeks.append(iso_week(week))
        week += timedelta(weeks=1)
    return {"weeks": calendar_weeks, "promotions": promotions}


@app.get(f"{API_PREFIX}/admin/pipelines")
async def pipelines(user: CurrentUser) -> dict[str, Any]:
    require_role(user, "ADMIN")
    with DB_LOCK, connect() as db:
        result = []
        for pipeline in db.execute("SELECT * FROM pipeline ORDER BY id"):
            last = db.execute(
                "SELECT * FROM pipeline_run WHERE pipeline_id=? ORDER BY id DESC LIMIT 1",
                (pipeline["id"],),
            ).fetchone()
            result.append(
                {
                    **dict(pipeline),
                    "config_json": json.loads(pipeline["config_json"]),
                    "last_run": dict(last) if last else None,
                    "next_run_at": next_pipeline_run(pipeline),
                }
            )
    return {"pipelines": result}


def validate_user_access(
    db: sqlite3.Connection,
    sales_org_access: list[str],
    assignments: list[UserAccessAssignment],
) -> list[tuple[str, int]]:
    sales_orgs = set(sales_org_access)
    known_sales_orgs = {
        row["p10_sales_org"]
        for row in db.execute("SELECT p10_sales_org FROM market WHERE active=1")
    }
    if len(sales_orgs) != len(sales_org_access) or not sales_orgs <= known_sales_orgs:
        raise HTTPException(status_code=422, detail="Invalid or duplicate sales organization access")
    pairs = [(assignment.market_code, assignment.customer_id) for assignment in assignments]
    if len(pairs) != len(set(pairs)):
        raise HTTPException(status_code=422, detail="Duplicate plan-account assignments")
    for market_code, customer_id in pairs:
        assignment_row = db.execute(
            "SELECT m.p10_sales_org FROM customer_l04 c "
            "JOIN market m ON m.code=c.market_code "
            "WHERE c.market_code=? AND c.id=? AND c.active=1 AND m.active=1",
            (market_code, customer_id),
        ).fetchone()
        if assignment_row is None:
            raise HTTPException(
                status_code=422, detail=f"Invalid plan-account assignment: {market_code}/{customer_id}"
            )
        if assignment_row["p10_sales_org"] not in sales_orgs:
            raise HTTPException(
                status_code=422,
                detail=f"Sales organization access is required for plan account {market_code}/{customer_id}",
            )
    return pairs


def validate_admin_sales_org_access(
    admin_sales_org_access: list[str], sales_org_access: list[str]
) -> list[str]:
    admin_orgs = set(admin_sales_org_access)
    if len(admin_orgs) != len(admin_sales_org_access):
        raise HTTPException(status_code=422, detail="Duplicate administrator sales organization access")
    if not admin_orgs.issubset(set(sales_org_access)):
        raise HTTPException(
            status_code=422,
            detail="Administrator access must be included in the user's sales organization access",
        )
    return sorted(admin_orgs)


def master_file_rows(filename: str, contents: bytes) -> list[tuple[int, dict[str, str]]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV must use UTF-8 encoding") from exc
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("The file must contain a header row")
        return [
            (row_number, {re.sub(r"[^a-z0-9]", "", (key or "").lower()): (value or "").strip()
                          for key, value in row.items() if key})
            for row_number, row in enumerate(reader, start=2)
            if any(value and value.strip() for value in row.values() if value is not None)
        ]
    if suffix != ".xlsx":
        raise ValueError("Upload a CSV or XLSX file")
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 50_000_000:
                raise ValueError("Expanded XLSX file is too large")
            names = set(archive.namelist())
            if "xl/worksheets/sheet1.xml" not in names:
                raise ValueError("The XLSX workbook does not contain Sheet1")
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.text or "" for node in item.iter()
                            if node.tag.endswith("}t") or node.tag == "t")
                    for item in shared_root
                ]
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            grid: list[list[str]] = []
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                values: dict[int, str] = {}
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    cell_ref = cell.attrib.get("r", "")
                    letters = re.match(r"[A-Z]+", cell_ref)
                    if not letters:
                        continue
                    column = 0
                    for character in letters.group():
                        column = column * 26 + ord(character) - 64
                    cell_type = cell.attrib.get("t")
                    value_node = next((part for part in cell if part.tag.endswith("}v")), None)
                    if cell_type == "inlineStr":
                        value = "".join(
                            part.text or ""
                            for part in cell.iter()
                            if part.tag.endswith("}t")
                        )
                    elif value_node is None or value_node.text is None:
                        value = ""
                    elif cell_type == "s":
                        value = shared[int(value_node.text)]
                    else:
                        value = value_node.text
                    values[column - 1] = value.strip()
                if values:
                    grid.append([values.get(index, "") for index in range(max(values) + 1)])
    except (zipfile.BadZipFile, ET.ParseError, IndexError, KeyError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Unable to read the XLSX workbook; export a valid .xlsx file") from exc
    if not grid or not grid[0]:
        raise ValueError("The workbook must contain a header row on its first sheet")
    headers = [re.sub(r"[^a-z0-9]", "", header.lower()) for header in grid[0]]
    return [
        (row_number, dict(zip(headers, values)))
        for row_number, values in enumerate(grid[1:], start=2)
        if any(value for value in values)
    ]


def required_master_value(row: dict[str, str], *headers: str) -> str:
    for header in headers:
        value = row.get(re.sub(r"[^a-z0-9]", "", header.lower()), "")
        if value:
            return value.strip()
    raise ValueError(f"Missing required column/value: {headers[0]}")


def fail_managed_file(file_id: int, message: str) -> None:
    with DB_LOCK, connect() as db:
        db.execute(
            "UPDATE managed_file SET status='FAILED',processed_at=?,message=? WHERE id=?",
            (utcnow().isoformat(), message[:1000], file_id),
        )


def apply_customer_master(db: sqlite3.Connection, data: list[tuple[int, dict[str, str]]]) -> int:
    rows: list[tuple[int, str, str, str, str | None]] = []
    markets = {row["code"] for row in db.execute("SELECT code FROM market WHERE active=1")}
    for row_number, row in data:
        try:
            market = required_master_value(
                row, "Market Code", "Market", "Sales Organization", "Sales Org"
            )
            if market not in markets:
                market_row = db.execute(
                    "SELECT code FROM market WHERE p10_sales_org=? AND active=1", (market,)
                ).fetchone()
                if market_row:
                    market = str(market_row["code"])
            external_code = required_master_value(
                row,
                "Plan Account Code L04",
                "Plan Account L04",
                "Customer L04",
                "Customer ID",
                "Customer Number",
                "Account Code",
            )
            name = required_master_value(row, "Plan Account Name", "Customer Name", "Name")
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: {exc}") from exc
        if market not in markets:
            raise ValueError(f"Row {row_number}: unknown or inactive market {market}")
        parent = next(
            (value for key, value in row.items() if key in {"parentl03", "customerl03", "l03"}),
            "",
        )
        rows.append((row_number, market, external_code, name, parent or None))
    if not rows:
        raise ValueError("The customer master file contains no data rows")
    for _, market, external_code, name, parent in rows:
        existing = db.execute(
            "SELECT id FROM customer_l04 WHERE market_code=? AND "
            "(external_code=? OR (external_code IS NULL AND name=?)) LIMIT 1",
            (market, external_code, name),
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE customer_l04 SET name=?,parent_l03=?,external_code=?,active=1,source_updated_at=? WHERE id=?",
                (name, parent, external_code, utcnow().isoformat(), existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO customer_l04(market_code,name,parent_l03,external_code,source_updated_at) "
                "VALUES(?,?,?,?,?)",
                (market, name, parent, external_code, utcnow().isoformat()),
            )
    return len(rows)


def ensure_product_hierarchy(db: sqlite3.Connection, code: str, description: str,
                             brand: str, sub_brand: str, category: str) -> str:
    path = [brand, sub_brand, category, "All Products", "All Products", "All Products",
            "All Products", "All Products"]
    parent: str | None = None
    for level, text in enumerate(path, start=1):
        identity = hashlib.sha256(f"{level}|{parent}|{text}".encode()).hexdigest()[:18]
        node_id = f"SAP-P{level}-{identity}"
        db.execute(
            "INSERT INTO product_hierarchy(node_id,parent_id,level,code,text) VALUES(?,?,?,?,?) "
            "ON CONFLICT(node_id) DO UPDATE SET text=excluded.text",
            (node_id, parent, level, text, text),
        )
        parent = node_id
    db.execute(
        "INSERT INTO product_hierarchy(node_id,parent_id,level,code,text) VALUES(?,?,9,?,?) "
        "ON CONFLICT(node_id) DO UPDATE SET parent_id=excluded.parent_id,text=excluded.text",
        (code, parent, code, description),
    )
    return code


def apply_product_master(db: sqlite3.Connection, data: list[tuple[int, dict[str, str]]]) -> int:
    rows: list[tuple[int, str, str, str, str, str, str, str, float | None]] = []
    for row_number, row in data:
        try:
            code = required_master_value(row, "Product P09", "P09 Code", "P09")
            description = required_master_value(row, "Product Description", "P09 Description", "Description")
            brand = required_master_value(row, "Brand")
            material = required_master_value(row, "Material Number", "P10 Material", "Material P10")
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: {exc}") from exc
        sub_brand = next((value for key, value in row.items() if key in {"subbrand", "subbrandname"}), "") or brand
        category = next((value for key, value in row.items() if key in {"category", "productcategory"}), "") or "Uncategorized"
        material_description = next((value for key, value in row.items() if key in {"materialdescription", "p10description"}), "") or description
        share_text = next((value for key, value in row.items() if key in {"splitshare", "share"}), "")
        try:
            share = float(share_text) if share_text else None
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: split share must be numeric") from exc
        if share is not None and not 0 <= share <= 100:
            raise ValueError(f"Row {row_number}: split share must be between 0 and 100")
        rows.append((row_number, code, description, brand, sub_brand, category, material, material_description, share))
    if not rows:
        raise ValueError("The product master file contains no data rows")
    material_shares: dict[str, dict[str, float]] = {}
    products_with_share: set[str] = set()
    for row_number, code, description, brand, sub_brand, category, material, material_description, share in rows:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", code):
            raise ValueError(f"Row {row_number}: invalid P09 product code")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,50}", material):
            raise ValueError(f"Row {row_number}: invalid P10 material number")
        if share is not None:
            products_with_share.add(code)
            if material in material_shares.setdefault(code, {}):
                raise ValueError(f"Row {row_number}: duplicate P10 material {material} with split shares")
            material_shares[code][material] = share
        node = ensure_product_hierarchy(db, code, description, brand, sub_brand, category)
        db.execute(
            "INSERT INTO product_p09(code,description,brand,sub_brand,category,hierarchy_node_id,active) "
            "VALUES(?,?,?,?,?,?,1) ON CONFLICT(code) DO UPDATE SET description=excluded.description,"
            "brand=excluded.brand,sub_brand=excluded.sub_brand,category=excluded.category,"
            "hierarchy_node_id=excluded.hierarchy_node_id,active=1",
            (code, description, brand, sub_brand, category, node),
        )
        owner = db.execute("SELECT p09_code FROM material_p10 WHERE material=?", (material,)).fetchone()
        if owner and owner["p09_code"] != code:
            raise ValueError(f"Row {row_number}: P10 material {material} is assigned to another P09")
        db.execute(
            "INSERT INTO material_p10(material,description,p09_code,case_uom,active) VALUES(?,?,?,'CS',1) "
            "ON CONFLICT(material) DO UPDATE SET description=excluded.description,p09_code=excluded.p09_code,active=1",
            (material, material_description, code),
        )
    for code in {row[1] for row in rows}:
        materials = [
            row["material"]
            for row in db.execute(
                "SELECT material FROM material_p10 WHERE p09_code=? AND active=1 ORDER BY material",
                (code,),
            )
        ]
        if code in products_with_share:
            supplied = material_shares[code]
            if set(supplied) != set(materials):
                raise ValueError(f"Product {code}: provide split shares for every active P10 material or none")
            total = sum(supplied.values())
            if abs(total - 100) > 0.01:
                raise ValueError(f"Product {code}: supplied material shares must total 100% (got {total:g}%)")
            for material, share in supplied.items():
                db.execute(
                    "INSERT INTO p09_p10_split(p09_code,material,share,valid_from,source) "
                    "VALUES(?,?,?,?,'MANUAL') ON CONFLICT(p09_code,material,valid_from) "
                    "DO UPDATE SET share=excluded.share,source='MANUAL'",
                    (code, material, share, date.today().isoformat()),
                )
            continue
        manual_shares: dict[str, float] = {}
        for row in db.execute(
            "SELECT material,share FROM p09_p10_split WHERE p09_code=? AND source='MANUAL' "
            "AND valid_from<=? ORDER BY valid_from DESC",
            (code, date.today().isoformat()),
        ):
            manual_shares.setdefault(row["material"], float(row["share"]))
        manual_total = sum(manual_shares.values())
        remaining = [material for material in materials if material not in manual_shares]
        if manual_total > 100.01 or (not remaining and manual_total < 99.99):
            raise ValueError(f"Product {code}: existing manual material shares must total 100%")
        calculated_share = (100 - manual_total) / len(remaining) if remaining else 0
        for material in remaining:
            db.execute(
                "INSERT INTO p09_p10_split(p09_code,material,share,valid_from,source) "
                "VALUES(?,?,?,?,'CALC') ON CONFLICT(p09_code,material,valid_from) "
                "DO UPDATE SET share=excluded.share,source='CALC'",
                (code, material, calculated_share, date.today().isoformat()),
            )
    return len(rows)


def process_master_file(file_id: int, user_email: str) -> dict[str, Any]:
    with DB_LOCK, connect() as db:
        record = db.execute("SELECT * FROM managed_file WHERE id=?", (file_id,)).fetchone()
        if record is None:
            raise HTTPException(status_code=404, detail="File not found")
        if record["direction"] != "INBOUND" or record["status"] not in {"QUEUED", "FAILED"}:
            raise HTTPException(status_code=409, detail="Only queued or failed inbound files can be processed")
        with db:
            db.execute(
                "UPDATE managed_file SET status='PROCESSING',message=NULL WHERE id=?",
                (file_id,),
            )
        source = Path(record["stored_path"])
        if source.parent.resolve() != INBOUND_QUEUE_DIR.resolve() or not source.is_file():
            raise HTTPException(status_code=404, detail="Queued file is missing from the inbound queue")
        filename = record["original_name"]
        category = record["category"]
        file_bytes = source.read_bytes()
        try:
            data = master_file_rows(filename, file_bytes)
            with db:
                count = (
                    apply_customer_master(db, data)
                    if category == "CUSTOMER_MASTER"
                    else apply_product_master(db, data)
                )
                db.execute(
                    "UPDATE managed_file SET row_count=?,message=? WHERE id=?",
                    (count, f"Validated and applied {count} rows", file_id),
                )
                audit(db, "master_file", str(file_id), "PROCESS", user_email,
                      after={"category": category, "rows": count})
        except ValueError as exc:
            message = str(exc)
            fail_managed_file(file_id, message)
            raise HTTPException(status_code=422, detail=message) from exc
        except sqlite3.IntegrityError as exc:
            message = "The extract contains a master-data row that conflicts with existing records"
            fail_managed_file(file_id, message)
            raise HTTPException(status_code=422, detail=message) from exc
        destination = INBOUND_PROCESSED_DIR / source.name
        source.replace(destination)
        with db:
            db.execute(
                "UPDATE managed_file SET stored_path=?,status='PROCESSED',processed_at=? WHERE id=?",
                (str(destination), utcnow().isoformat(), file_id),
            )
    return {"id": file_id, "status": "PROCESSED", "rows": count}


@app.post(f"{API_PREFIX}/admin/master-data/{{master_type}}/upload", status_code=201)
async def upload_master_file(
    master_type: Literal["customer", "product"],
    payload: MasterFileUpload,
    user: CurrentUser,
) -> dict[str, Any]:
    require_role(user, "ADMIN")
    name = Path(payload.filename.replace("\\", "/")).name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,199}", name):
        raise HTTPException(status_code=422, detail="A valid source filename is required")
    try:
        contents = base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The upload is not valid base64 data") from exc
    if not contents or len(contents) > 10_000_000:
        raise HTTPException(status_code=413, detail="Master extract must be between 1 byte and 10 MB")
    if Path(name).suffix.lower() not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Upload a CSV or XLSX master extract")
    try:
        master_file_rows(name, contents)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    file_id = secrets.token_hex(16)
    destination = INBOUND_QUEUE_DIR / f"{file_id}{Path(name).suffix.lower()}"
    destination.write_bytes(contents)
    category = "CUSTOMER_MASTER" if master_type == "customer" else "PRODUCT_MASTER"
    try:
        with DB_LOCK, connect() as db:
            with db:
                cursor = db.execute(
                    "INSERT INTO managed_file(direction,category,original_name,stored_path,status,uploaded_by,created_at) "
                    "VALUES('INBOUND',?,?,?,'QUEUED',?,?)",
                    (category, name, str(destination), user["email"], utcnow().isoformat()),
                )
                row_id = int(cursor.lastrowid)
                audit(db, "master_file", str(row_id), "UPLOAD", user["email"],
                      after={"category": category, "filename": name})
    except sqlite3.Error:
        destination.unlink(missing_ok=True)
        raise
    return {"id": row_id, "filename": name, "status": "QUEUED", "queue_folder": "Inbound Queue"}


@app.get(f"{API_PREFIX}/admin/files")
async def managed_files(user: CurrentUser) -> dict[str, Any]:
    require_role(user, "ADMIN")
    with DB_LOCK, connect() as db:
        records = [
            dict(row)
            for row in db.execute(
                "SELECT id,direction,category,original_name,status,uploaded_by,created_at,"
                "processed_at,row_count,message FROM managed_file ORDER BY id DESC LIMIT 500"
            )
        ]
    return {"files": records}


@app.post(f"{API_PREFIX}/admin/files/{{file_id}}/process")
async def process_queued_master_file(file_id: int, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "ADMIN")
    return process_master_file(file_id, user["email"])


@app.get(f"{API_PREFIX}/admin/files/{{file_id}}/download")
async def download_managed_file(file_id: int, user: CurrentUser) -> Response:
    require_role(user, "ADMIN")
    with DB_LOCK, connect() as db:
        record = db.execute("SELECT * FROM managed_file WHERE id=?", (file_id,)).fetchone()
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    stored = Path(record["stored_path"]).resolve()
    allowed_roots = [INBOUND_QUEUE_DIR.resolve(), INBOUND_PROCESSED_DIR.resolve(), OUTBOUND_DIR.resolve()]
    if not any(stored.parent == root for root in allowed_roots) or not stored.is_file():
        raise HTTPException(status_code=404, detail="File is not available")
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if stored.suffix == ".xlsx" else "text/csv"
    return Response(
        stored.read_bytes(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{record["original_name"]}"'},
    )


@app.post(f"{API_PREFIX}/admin/users", status_code=201)
async def create_admin_user(payload: AdminUserCreate, user: CurrentUser) -> dict[str, Any]:
    require_access_administrator(user)
    email = payload.email.strip().lower()
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="User name must contain at least 2 characters")
    with DB_LOCK, connect() as db:
        with db:
            pairs = validate_user_access(db, payload.sales_org_access, payload.assignments)
            requested_admin_orgs = validate_admin_sales_org_access(
                payload.admin_sales_org_access, payload.sales_org_access
            )
            if db.execute(
                "SELECT 1 FROM app_user WHERE email=? COLLATE NOCASE", (email,)
            ).fetchone():
                raise HTTPException(status_code=409, detail="A user with this email already exists")
            cursor = db.execute(
                "INSERT INTO app_user(email,name,role,password_hash,active,last_login_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    email,
                    name,
                    payload.role,
                    password_hash(payload.password),
                    int(payload.active),
                    utcnow().isoformat(),
                ),
            )
            user_id = int(cursor.lastrowid)
            db.executemany(
                "INSERT INTO user_sales_org(user_id,sales_org) VALUES(?,?)",
                [(user_id, sales_org) for sales_org in sorted(set(payload.sales_org_access))],
            )
            first_admin_orgs = [
                sales_org
                for sales_org in sorted(set(payload.sales_org_access))
                if not db.execute(
                    "SELECT 1 FROM user_sales_org so JOIN app_user u ON u.id=so.user_id "
                    "WHERE so.sales_org=? AND so.user_id<>? AND u.is_seed=0 LIMIT 1",
                    (sales_org, user_id),
                ).fetchone()
            ]
            effective_admin_orgs = sorted(set(requested_admin_orgs) | set(first_admin_orgs))
            db.executemany(
                "INSERT INTO user_sales_org_admin(user_id,sales_org) VALUES(?,?)",
                [(user_id, sales_org) for sales_org in effective_admin_orgs],
            )
            db.executemany(
                "INSERT INTO user_assignment(user_id,market_code,customer_id) VALUES(?,?,?)",
                [(user_id, market_code, customer_id) for market_code, customer_id in pairs],
            )
            audit(
                db,
                "app_user",
                str(user_id),
                "CREATE",
                user["email"],
                after={
                    "email": email,
                    "name": name,
                    "role": payload.role,
                    "sales_org_access": payload.sales_org_access,
                    "assignments": pairs,
                    "admin_sales_org_access": effective_admin_orgs,
                },
            )
    return {
        "id": user_id,
        "email": email,
        "name": name,
        "role": payload.role,
        "sales_org_access": sorted(set(payload.sales_org_access)),
        "admin_sales_org_access": effective_admin_orgs,
        "first_admin_sales_orgs": first_admin_orgs,
        "assignments": len(pairs),
    }


@app.put(f"{API_PREFIX}/admin/pipelines/{{pipeline_id}}")
async def update_pipeline(
    pipeline_id: str, payload: PipelineUpdate, user: CurrentUser
) -> dict[str, Any]:
    require_role(user, "ADMIN")
    try:
        ZoneInfo(payload.schedule_timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown schedule timezone") from exc
    if payload.schedule_start_date and payload.schedule_end_date and payload.schedule_end_date < payload.schedule_start_date:
        raise HTTPException(status_code=422, detail="Schedule end date must be on or after its start date")
    with DB_LOCK, connect() as db:
        with db:
            current = db.execute(
                "SELECT config_json,direction,connector_type FROM pipeline WHERE id=?", (pipeline_id,)
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Pipeline not found")
            config = json.loads(current["config_json"])
            file_path = payload.file_path if payload.file_path is not None else config.get("file_path")
            resolved_path = validate_pipeline_file_location(file_path, current["direction"])
            if current["connector_type"] == "FileConnector" and resolved_path is None:
                raise HTTPException(status_code=422, detail="FileConnector requires an ArBa file location")
            if current["connector_type"] == "FileConnector" and resolved_path:
                if resolved_path.suffix.lower() not in {".csv", ".xlsx"}:
                    raise HTTPException(status_code=422, detail="FileConnector files must use .csv or .xlsx")
            if payload.file_path is not None:
                config["file_path"] = payload.file_path.strip() or None
            cursor = db.execute(
                "UPDATE pipeline SET enabled=?,schedule_frequency=?,schedule_timezone=?,schedule_time=?,"
                "schedule_weekday=?,schedule_month_day=?,schedule_quarter_month=?,schedule_start_date=?,"
                "schedule_end_date=?,last_schedule_key=NULL,config_json=?,"
                "schedule_cron=? WHERE id=?",
                (
                    int(payload.enabled),
                    payload.schedule_frequency,
                    payload.schedule_timezone,
                    payload.schedule_time,
                    payload.schedule_weekday,
                    payload.schedule_month_day,
                    payload.schedule_quarter_month,
                    payload.schedule_start_date.isoformat() if payload.schedule_start_date else None,
                    payload.schedule_end_date.isoformat() if payload.schedule_end_date else None,
                    json.dumps(config),
                    f"{payload.schedule_time} {payload.schedule_frequency}",
                    pipeline_id,
                ),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Pipeline not found")
            audit(
                db,
                "pipeline",
                pipeline_id,
                "UPDATE",
                user["email"],
                after=payload.model_dump(),
            )
    return {"id": pipeline_id, **payload.model_dump()}


@app.post(f"{API_PREFIX}/admin/pipelines", status_code=201)
async def create_pipeline(payload: PipelineCreate, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "ADMIN")
    try:
        ZoneInfo(payload.schedule_timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown schedule timezone") from exc
    if payload.schedule_start_date and payload.schedule_end_date and payload.schedule_end_date < payload.schedule_start_date:
        raise HTTPException(status_code=422, detail="Schedule end date must be on or after its start date")
    validate_pipeline_file_location(payload.file_path, payload.direction)
    if payload.connector_type == "FileConnector" and not payload.file_path:
        raise HTTPException(status_code=422, detail="FileConnector requires an ArBa file location")
    if payload.connector_type == "FileConnector" and Path(payload.file_path).suffix.lower() not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=422, detail="FileConnector files must use .csv or .xlsx")
    pipeline_id = f"CUSTOM-{secrets.token_hex(4).upper()}"
    config = {"file_path": payload.file_path.strip() if payload.file_path else None}
    with DB_LOCK, connect() as db:
        with db:
            db.execute(
                "INSERT INTO pipeline(id,name,direction,source,target,connector_type,schedule_cron,enabled,"
                "config_json,schedule_frequency,schedule_timezone,schedule_time,schedule_weekday,"
                "schedule_month_day,schedule_quarter_month,schedule_start_date,schedule_end_date) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pipeline_id,
                    payload.name.strip(),
                    payload.direction,
                    payload.source.strip(),
                    payload.target.strip(),
                    payload.connector_type,
                    f"{payload.schedule_time} {payload.schedule_frequency}",
                    int(payload.enabled),
                    json.dumps(config),
                    payload.schedule_frequency,
                    payload.schedule_timezone,
                    payload.schedule_time,
                    payload.schedule_weekday,
                    payload.schedule_month_day,
                    payload.schedule_quarter_month,
                    payload.schedule_start_date.isoformat() if payload.schedule_start_date else None,
                    payload.schedule_end_date.isoformat() if payload.schedule_end_date else None,
                ),
            )
            audit(
                db,
                "pipeline",
                pipeline_id,
                "CREATE",
                user["email"],
                after={**payload.model_dump(), "config_json": config},
            )
    return {"id": pipeline_id, **payload.model_dump(), "config_json": config}


@app.post(f"{API_PREFIX}/admin/pipelines/{{pipeline_id}}/run")
async def run_pipeline(
    pipeline_id: str,
    user: CurrentUser,
    dry_run: bool = True,
    trigger: Literal["MANUAL", "SCHEDULE"] = "MANUAL",
) -> dict[str, Any]:
    require_role(user, "ADMIN")
    started = utcnow().isoformat()
    outbound_rows: list[dict[str, str]] = []
    outbound_market = ""
    custom_outbound: list[tuple[str, dict[str, str]]] = []
    custom_inbound_archive: tuple[Path, str, int] | None = None
    with DB_LOCK, connect() as db:
        with db:
            pipeline = db.execute("SELECT * FROM pipeline WHERE id=?", (pipeline_id,)).fetchone()
            if not pipeline:
                raise HTTPException(status_code=404, detail="Pipeline not found")
            cursor = db.execute(
                "INSERT INTO pipeline_run(pipeline_id,trigger,status,started_at,message) VALUES(?,?,'RUNNING',?,?)",
                (
                    pipeline_id,
                    trigger,
                    started,
                    "Dry run" if dry_run else "Mock connector execution",
                ),
            )
            run_id = int(cursor.lastrowid)
            count = db.execute("SELECT COUNT(*) AS n FROM market WHERE active=1").fetchone()["n"]
            status_value = "SUCCESS"
            message = f"Mock {pipeline['connector_type']} completed; dry_run={str(dry_run).lower()}"
            if pipeline_id == "OUT-01":
                try:
                    outbound_market = db.execute(
                        "SELECT code FROM market WHERE active=1 ORDER BY code LIMIT 1"
                    ).fetchone()["code"]
                    rows = build_p10_rows(
                        db,
                        outbound_market,
                    )
                    outbound_rows = rows
                    if not dry_run:
                        db.executemany(
                            "INSERT INTO p10_outbound(run_id,market_code,start_date,end_date,plan_account,material,base,lift,total,promo_number,cons_start,cons_end,sales_org) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [
                                (
                                    run_id,
                                    outbound_market,
                                    r["Start Date"][:10],
                                    r["End Date"][:10],
                                    r["Plan Account"],
                                    r["Material Number"],
                                    int(r["BaseVolume"]),
                                    int(r["LiftVolume"]),
                                    int(r["TotalVolume"]),
                                    r["PromoNumber"],
                                    r["Consumption Start"][:10],
                                    r["Consumption End"][:10],
                                    r["Sales Org"],
                                )
                                for r in rows
                            ],
                        )
                    count = len(rows)
                except HTTPException as exc:
                    status_value = "FAILED"
                    message = str(exc.detail)
                    count = 0
            elif pipeline["connector_type"] == "FileConnector":
                config = json.loads(pipeline["config_json"])
                path_error = None
                try:
                    configured_path = validate_pipeline_file_location(
                        config.get("file_path"), pipeline["direction"]
                    )
                except HTTPException as exc:
                    configured_path = None
                    path_error = str(exc.detail)
                if configured_path is None:
                    status_value = "FAILED"
                    message = path_error or "FileConnector has no configured file location"
                    count = 0
                elif configured_path.suffix.lower() not in {".csv", ".xlsx"}:
                    status_value = "FAILED"
                    message = "FileConnector files must use .csv or .xlsx"
                    count = 0
                elif pipeline["direction"] == "INBOUND":
                    try:
                        if not configured_path.is_file():
                            raise FileNotFoundError(f"Configured inbound file does not exist: {configured_path}")
                        parsed_rows = master_file_rows(
                            configured_path.name, configured_path.read_bytes()
                        )
                        count = len(parsed_rows)
                        if not dry_run:
                            archived_path = INBOUND_PROCESSED_DIR / (
                                f"{secrets.token_hex(8)}_{Path(configured_path.name).name}"
                            )
                            configured_path.replace(archived_path)
                            custom_inbound_archive = (
                                archived_path,
                                configured_path.name,
                                count,
                            )
                            status_value = "PARTIAL"
                            message = (
                                f"Validated and archived {count} rows. A target-specific "
                                "master-data mapping is required to load these rows into ArBa."
                            )
                        else:
                            message = f"Validated {count} rows from {configured_path.name}; no data was changed."
                    except (OSError, ValueError) as exc:
                        status_value = "FAILED"
                        message = str(exc)
                        count = 0
                elif pipeline["direction"] == "OUTBOUND":
                    try:
                        for market_row in db.execute(
                            "SELECT code,p10_sales_org FROM market WHERE active=1 ORDER BY code"
                        ):
                            rows = build_p10_rows(db, market_row["code"])
                            custom_outbound.extend(
                                (market_row["code"], row) for row in rows
                            )
                        count = len(custom_outbound)
                        if not dry_run:
                            if configured_path.suffix.lower() == ".xlsx":
                                content = build_xlsx([row for _, row in custom_outbound])
                            elif configured_path.suffix.lower() == ".csv":
                                output = io.StringIO(newline="")
                                writer = csv.DictWriter(output, fieldnames=P10_COLUMNS)
                                writer.writeheader()
                                writer.writerows(row for _, row in custom_outbound)
                                content = output.getvalue().encode("utf-8-sig")
                            else:
                                raise ValueError("Outbound FileConnector location must end in .csv or .xlsx")
                            configured_path.parent.mkdir(parents=True, exist_ok=True)
                            configured_path.write_bytes(content)
                            db.executemany(
                                "INSERT INTO p10_outbound(run_id,market_code,start_date,end_date,plan_account,material,base,lift,total,promo_number,cons_start,cons_end,sales_org) "
                                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                [
                                    (
                                        run_id,
                                        market_code,
                                        row["Start Date"][:10],
                                        row["End Date"][:10],
                                        row["Plan Account"],
                                        row["Material Number"],
                                        int(row["BaseVolume"]),
                                        int(row["LiftVolume"]),
                                        int(row["TotalVolume"]),
                                        row["PromoNumber"],
                                        row["Consumption Start"][:10],
                                        row["Consumption End"][:10],
                                        row["Sales Org"],
                                    )
                                    for market_code, row in custom_outbound
                                ],
                            )
                            db.execute(
                                "INSERT INTO managed_file(direction,category,original_name,stored_path,status,uploaded_by,created_at,processed_at,row_count,message) "
                                "VALUES('OUTBOUND',?,?,?,'PROCESSED',?,?,?,?,?)",
                                (
                                    pipeline_id,
                                    configured_path.name,
                                    str(configured_path),
                                    user["email"],
                                    utcnow().isoformat(),
                                    utcnow().isoformat(),
                                    count,
                                    f"Generated by pipeline {pipeline_id}",
                                ),
                            )
                            message = f"Wrote {count} P10 rows to {configured_path}"
                        else:
                            message = f"Prepared {count} P10 rows; no file was written."
                    except (OSError, ValueError, HTTPException) as exc:
                        status_value = "FAILED"
                        message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                        count = 0
            db.execute(
                "UPDATE pipeline_run SET status=?,finished_at=?,rows_read=?,rows_written=?,rows_rejected=0,message=? WHERE id=?",
                (
                    status_value,
                    utcnow().isoformat(),
                    count,
                    0 if dry_run else count,
                    message,
                    run_id,
                ),
            )
            audit(
                db,
                "pipeline_run",
                str(run_id),
                trigger,
                user["email"],
                after={
                    "pipeline": pipeline_id,
                    "dry_run": dry_run,
                    "status": status_value,
                },
            )
            if custom_inbound_archive is not None:
                archive, original_name, rows_written = custom_inbound_archive
                db.execute(
                    "INSERT INTO managed_file(direction,category,original_name,stored_path,status,uploaded_by,created_at,processed_at,row_count,message) "
                    "VALUES('INBOUND',?,?,?,'PROCESSED',?,?,?,?,?)",
                    (
                        pipeline_id,
                        original_name,
                        str(archive),
                        user["email"],
                        started,
                        utcnow().isoformat(),
                        rows_written,
                        "Validated and archived; no target-specific master-data mapping is configured.",
                    ),
                )
    if pipeline_id == "OUT-01" and not dry_run and status_value == "SUCCESS":
        try:
            store_outbound_file(
                f"arba_p10_{outbound_market}_run_{run_id}.xlsx",
                "OUT-01",
                build_xlsx(outbound_rows),
                user["email"],
            )
        except (OSError, sqlite3.Error):
            logger.exception("Unable to store outbound file for pipeline run %s", run_id)
            status_value = "FAILED"
            message = "P10 payload was generated but could not be stored in Outbound Files"
            with DB_LOCK, connect() as db:
                db.execute(
                    "UPDATE pipeline_run SET status='FAILED',finished_at=?,message=? WHERE id=?",
                    (utcnow().isoformat(), message, run_id),
                )
    return {"run_id": run_id, "status": status_value, "message": message}


@app.get(f"{API_PREFIX}/admin/users")
async def admin_users(user: CurrentUser) -> dict[str, Any]:
    require_access_administrator(user)
    with DB_LOCK, connect() as db:
        users = []
        user_query = "SELECT id,email,name,role,active,last_login_at FROM app_user"
        if user["role"] != "ADMIN":
            user_query += " WHERE role<>'ADMIN'"
        user_query += " ORDER BY email"
        for row in db.execute(user_query):
            result = dict(row)
            result["sales_org_access"] = [
                item["sales_org"]
                for item in db.execute(
                    "SELECT sales_org FROM user_sales_org WHERE user_id=? ORDER BY sales_org",
                    (row["id"],),
                )
            ]
            result["admin_sales_org_access"] = [
                item["sales_org"]
                for item in db.execute(
                    "SELECT sales_org FROM user_sales_org_admin WHERE user_id=? ORDER BY sales_org",
                    (row["id"],),
                )
            ]
            users.append(result)
        assignments = [
            dict(r)
            for r in db.execute(
                "SELECT ua.user_id,u.email,ua.market_code,ua.customer_id,c.name AS customer_name "
                "FROM user_assignment ua JOIN app_user u ON u.id=ua.user_id "
                "JOIN customer_l04 c ON c.id=ua.customer_id ORDER BY u.email,ua.market_code,c.name"
            )
        ]
        sales_orgs = [
            dict(row)
            for row in db.execute(
                "SELECT p10_sales_org AS code,name FROM market WHERE active=1 ORDER BY p10_sales_org"
            )
        ]
    return {"users": users, "assignments": assignments, "sales_orgs": sales_orgs}


@app.put(f"{API_PREFIX}/admin/users/{{user_id}}")
async def update_admin_user(
    user_id: int, payload: AdminUserUpdate, user: CurrentUser
) -> dict[str, Any]:
    require_access_administrator(user)
    with DB_LOCK, connect() as db:
        with db:
            pairs = validate_user_access(db, payload.sales_org_access, payload.assignments)
            admin_orgs = validate_admin_sales_org_access(
                payload.admin_sales_org_access, payload.sales_org_access
            )
            target = db.execute(
                "SELECT id,email,name,role,active FROM app_user WHERE id=?", (user_id,)
            ).fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail="User not found")
            current_sales_orgs = {
                row["sales_org"]
                for row in db.execute(
                    "SELECT sales_org FROM user_sales_org WHERE user_id=?",
                    (user_id,),
                )
            }
            if user["role"] != "ADMIN" and target["role"] == "ADMIN":
                raise HTTPException(
                    status_code=403,
                    detail="Only a system administrator can change a system administrator account",
                )
            if user["role"] != "ADMIN" and payload.role == "ADMIN":
                raise HTTPException(
                    status_code=403,
                    detail="Use administrator sales organization access instead of the global system administrator role",
                )
            if user["role"] != "ADMIN":
                current_admin_orgs = {
                    row["sales_org"]
                    for row in db.execute(
                        "SELECT sales_org FROM user_sales_org_admin WHERE user_id=?",
                        (user_id,),
                    )
                }
                removed_admin_orgs = current_admin_orgs - set(admin_orgs)
                if not payload.active:
                    removed_admin_orgs.update(current_admin_orgs)
                for sales_org in removed_admin_orgs:
                    replacement = db.execute(
                        "SELECT 1 FROM app_user u "
                        "LEFT JOIN user_sales_org_admin usa ON usa.user_id=u.id "
                        "WHERE u.active=1 AND u.id<>? AND "
                        "(u.role='ADMIN' OR usa.sales_org=?) LIMIT 1",
                        (user_id, sales_org),
                    ).fetchone()
                    if replacement is None:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Assign another active administrator to {sales_org} before removing the last one",
                        )
            first_admin_orgs = [
                sales_org
                for sales_org in sorted(set(payload.sales_org_access) - current_sales_orgs)
                if not db.execute(
                    "SELECT 1 FROM user_sales_org so JOIN app_user u ON u.id=so.user_id "
                    "WHERE so.sales_org=? AND so.user_id<>? AND u.is_seed=0 LIMIT 1",
                    (sales_org, user_id),
                ).fetchone()
            ]
            effective_admin_orgs = sorted(set(admin_orgs) | set(first_admin_orgs))
            for market_code, customer_id in pairs:
                assignment_exists = db.execute(
                    "SELECT 1 FROM customer_l04 WHERE market_code=? AND id=? AND active=1",
                    (market_code, customer_id),
                ).fetchone()
                if assignment_exists is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid plan-account assignment: {market_code}/{customer_id}",
                    )
            before = {
                "role": target["role"],
                "active": bool(target["active"]),
                "assignments": [
                    {"market_code": row["market_code"], "customer_id": row["customer_id"]}
                    for row in db.execute(
                        "SELECT market_code,customer_id FROM user_assignment WHERE user_id=?",
                        (user_id,),
                    )
                ],
                "sales_org_access": [
                    row["sales_org"]
                    for row in db.execute(
                        "SELECT sales_org FROM user_sales_org WHERE user_id=?",
                        (user_id,),
                    )
                ],
                "admin_sales_org_access": [
                    row["sales_org"]
                    for row in db.execute(
                        "SELECT sales_org FROM user_sales_org_admin WHERE user_id=?",
                        (user_id,),
                    )
                ],
            }
            db.execute(
                "UPDATE app_user SET role=?,active=? WHERE id=?",
                (payload.role, int(payload.active), user_id),
            )
            db.execute("DELETE FROM user_assignment WHERE user_id=?", (user_id,))
            db.executemany(
                "INSERT INTO user_assignment(user_id,market_code,customer_id) VALUES(?,?,?)",
                [(user_id, market_code, customer_id) for market_code, customer_id in pairs],
            )
            db.execute("DELETE FROM user_sales_org WHERE user_id=?", (user_id,))
            db.executemany(
                "INSERT INTO user_sales_org(user_id,sales_org) VALUES(?,?)",
                [(user_id, sales_org) for sales_org in sorted(set(payload.sales_org_access))],
            )
            db.execute("DELETE FROM user_sales_org_admin WHERE user_id=?", (user_id,))
            db.executemany(
                "INSERT INTO user_sales_org_admin(user_id,sales_org) VALUES(?,?)",
                [(user_id, sales_org) for sales_org in effective_admin_orgs],
            )
            audit(
                db,
                "app_user",
                str(user_id),
                "UPDATE_ACCESS",
                user["email"],
                before=before,
                after={
                    **payload.model_dump(),
                    "admin_sales_org_access": effective_admin_orgs,
                },
            )
    return {
        "id": user_id,
        "role": payload.role,
        "active": payload.active,
        "assignments": len(pairs),
        "admin_sales_org_access": effective_admin_orgs,
        "first_admin_sales_orgs": first_admin_orgs,
    }


@app.get(f"{API_PREFIX}/admin/audit")
async def admin_audit(user: CurrentUser, limit: int = 100) -> dict[str, Any]:
    require_role(user, "ADMIN")
    limit = max(1, min(limit, 500))
    with DB_LOCK, connect() as db:
        rows = [
            dict(r)
            for r in db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        ]
    return {"events": rows}


@app.get(f"{API_PREFIX}/admin/pipelines/{{pipeline_id}}/runs")
async def pipeline_runs(pipeline_id: str, user: CurrentUser) -> dict[str, Any]:
    require_role(user, "ADMIN")
    with DB_LOCK, connect() as db:
        if not db.execute("SELECT 1 FROM pipeline WHERE id=?", (pipeline_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Pipeline not found")
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM pipeline_run WHERE pipeline_id=? ORDER BY id DESC LIMIT 100",
                (pipeline_id,),
            )
        ]
    return {"runs": rows}



if __name__ == "__main__":
    host = os.getenv("ARBA_HOST", "127.0.0.1")
    port = int(os.getenv("ARBA_PORT", "8171"))
    uvicorn.run(app, host=host, port=port)
