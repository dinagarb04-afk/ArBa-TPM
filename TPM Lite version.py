"""TPM Lite: a single-file, tenant-isolated promotion-planning web MVP.

Run locally with:  py "TPM Lite version.py"
Then open:         http://127.0.0.1:8000

For a hosted web service, configure the start command as
    python "TPM Lite version.py"
and set TPM_LITE_SECRET_KEY and TPM_LITE_DATA_DIR to a persistent disk path.
This MVP uses SQLite and synthetic demo master data; it is not a production
SAP/P10 integration or an enterprise deployment.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import local
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4


APP_NAME = "TPM Lite"
SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_FORM_BYTES = 32_768
MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.01")
SPEND_TYPES = {
    "rate": "Per-unit discount",
    "percent": "Percentage discount",
    "lump_sum": "Fixed lump sum",
}
SPEND_TREATMENTS = {
    "on_invoice": "On-invoice",
    "off_invoice": "Off-invoice",
}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$")
LOGGER = logging.getLogger("tpm_lite")
REQUEST_CONTEXT = local()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TPM_LITE_DATA_DIR", BASE_DIR / "tpm_lite_data"))
DATABASE_PATH = DATA_DIR / "tpm_lite.sqlite3"
SECRET_KEY = os.environ.get("TPM_LITE_SECRET_KEY")
IS_HOSTED = any(
    os.environ.get(name)
    for name in ("RENDER", "WEBSITE_INSTANCE_ID", "DYNO", "FLY_APP_NAME")
)
if not SECRET_KEY:
    if IS_HOSTED:
        raise RuntimeError(
            "Set TPM_LITE_SECRET_KEY to a long, random secret before deployment."
        )
    SECRET_KEY = secrets.token_urlsafe(48)
    LOGGER.warning(
        "TPM_LITE_SECRET_KEY is unset; sessions will expire when this process restarts."
    )
if len(SECRET_KEY) < 32:
    raise RuntimeError("TPM_LITE_SECRET_KEY must contain at least 32 characters.")


def utc_now() -> str:
    """Return a sortable, timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def initialize_database() -> None:
    with closing(db_connect()) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plan_accounts (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                currency TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (tenant_id, code)
            );
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                sku TEXT NOT NULL,
                name TEXT NOT NULL,
                uom TEXT NOT NULL,
                reference_price TEXT NOT NULL,
                reference_cost TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (tenant_id, sku)
            );
            CREATE TABLE IF NOT EXISTS promotions (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                account_id TEXT NOT NULL REFERENCES plan_accounts(id),
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Draft',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS promotion_items (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                promotion_id TEXT NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL REFERENCES products(id),
                baseline_volume TEXT NOT NULL,
                planned_volume TEXT NOT NULL,
                regular_price TEXT NOT NULL,
                unit_cost TEXT NOT NULL,
                spend_type TEXT NOT NULL,
                spend_amount TEXT NOT NULL,
                spend_treatment TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (promotion_id, product_id)
            );
            CREATE INDEX IF NOT EXISTS ix_promotions_tenant_created
                ON promotions (tenant_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_items_tenant_promotion
                ON promotion_items (tenant_id, promotion_id);
            """
        )
        connection.commit()


def password_digest(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), actual_salt, 310_000
    )
    return f"{base64.urlsafe_b64encode(actual_salt).decode()}:{base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    salt_text, digest_text = stored.split(":", 1)
    salt = base64.urlsafe_b64decode(salt_text.encode())
    expected = base64.urlsafe_b64decode(digest_text.encode())
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return hmac.compare_digest(actual, expected)


def decimal_input(value: str, label: str, *, minimum: Decimal = Decimal(0)) -> Decimal:
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        raise ValueError(f"Enter a valid {label}.") from None
    if not number.is_finite() or number < minimum or number > Decimal("999999999999"):
        raise ValueError(f"{label.capitalize()} must be at least {minimum}.")
    return number


def quantize(value: Decimal, quantum: Decimal = MONEY_QUANTUM) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def fmt_money(value: Decimal, currency: str) -> str:
    return f"{html.escape(currency)} {quantize(value):,.2f}"


def fmt_quantity(value: Decimal) -> str:
    return f"{quantize(value, QUANTITY_QUANTUM):,.2f}"


def calculate_item(item: sqlite3.Row) -> dict[str, Decimal | str]:
    """Calculate planning estimates without duplicating spend in net sales."""
    baseline = Decimal(item["baseline_volume"])
    planned = Decimal(item["planned_volume"])
    regular_price = Decimal(item["regular_price"])
    unit_cost = Decimal(item["unit_cost"])
    amount = Decimal(item["spend_amount"])
    spend_type = item["spend_type"]
    treatment = item["spend_treatment"]

    if spend_type == "rate":
        discount_per_unit = amount
        spend = amount * planned
    elif spend_type == "percent":
        discount_per_unit = regular_price * amount / Decimal(100)
        spend = discount_per_unit * planned
    else:
        spend = amount
        discount_per_unit = spend / planned if treatment == "on_invoice" else Decimal(0)

    landed_price = (
        regular_price - discount_per_unit
        if treatment == "on_invoice"
        else regular_price
    )
    gross_sales = regular_price * planned
    net_sales = (
        landed_price * planned
        if treatment == "on_invoice"
        else gross_sales - spend
    )
    cost = unit_cost * planned
    contribution = net_sales - cost
    baseline_contribution = (regular_price - unit_cost) * baseline
    incremental_contribution = contribution - baseline_contribution
    uplift = max(planned - baseline, Decimal(0))
    roi = incremental_contribution / spend if spend > 0 else None

    return {
        "uplift": quantize(uplift, QUANTITY_QUANTUM),
        "landed_price": quantize(landed_price),
        "gross_sales": quantize(gross_sales),
        "net_sales": quantize(net_sales),
        "spend": quantize(spend),
        "cost": quantize(cost),
        "contribution": quantize(contribution),
        "incremental_contribution": quantize(incremental_contribution),
        "roi": roi,
    }


def signed_session(claims: dict[str, Any]) -> str:
    payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signature = hmac.new(
        str(SECRET_KEY).encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def read_session(cookie_header: str) -> dict[str, Any] | None:
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
        token = cookie.get("tpm_session")
        if token is None:
            return None
        encoded, signature = token.value.split(".", 1)
        expected = hmac.new(
            str(SECRET_KEY).encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padding = "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded + padding))
        if not isinstance(claims, dict) or int(claims["exp"]) < int(time.time()):
            return None
        if not isinstance(claims.get("csrf"), str):
            return None
        return claims
    except (CookieError, ValueError, TypeError, KeyError, UnicodeError):
        return None


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def page_layout(
    title: str,
    body: str,
    user: sqlite3.Row | None = None,
    *,
    active: str = "",
    notice: str = "",
) -> str:
    nav = ""
    if user is not None:
        links = [
            ("/", "Overview", "overview"),
            ("/promotions", "Promotions", "promotions"),
            ("/accounts", "Plan accounts", "accounts"),
            ("/products", "OSKUs", "products"),
        ]
        nav = (
            '<aside class="sidebar"><a class="brand" href="/">'
            '<span class="brand-mark">T</span><span>TPM <b>Lite</b>'
            '<small>TRADE PLANNING</small></span></a>'
            '<div class="workspace-label">WORKSPACE</div><nav>'
            + "".join(
                f'<a class="nav-link {"selected" if key == active else ""}" href="{href}">'
                f'<span class="nav-dot"></span>{label}</a>'
                for href, label, key in links
            )
            + '</nav><div class="sidebar-bottom"><span class="demo-badge">'
            "SYNTHETIC DEMO DATA</span>"
            f'<span class="user-label">{escape(user["name"])}</span>'
            f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{escape(getattr(REQUEST_CONTEXT, "csrf", ""))}">'
            '<button class="text-button" type="submit">Sign out</button></form>'
            "</div></aside>"
        )
    alert = f'<div class="notice" role="status">{escape(notice)}</div>' if notice else ""
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)} · TPM Lite</title>"
        f"<style>{STYLES}</style></head><body>"
        f'{nav}<main class="{"app-main" if user is not None else "public-main"}">'
        f'{alert}{body}</main></body></html>'
    )


class RequestTooLarge(ValueError):
    """Raised when a submitted form exceeds the request-size limit."""


STYLES = """
:root{color-scheme:light;--ink:#172e40;--muted:#718090;--line:#e4eaf0;--paper:#fff;
--canvas:#f4f7f9;--teal:#0b827b;--teal-dark:#086b66;--mint:#e6f5f1;--navy:#102a3b;
--gold:#d6a74b;--red:#a34545;font-family:Inter,"Segoe UI",Arial,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font-size:14px}
a{color:inherit;text-decoration:none}button,input,select,textarea{font:inherit}
.sidebar{position:fixed;inset:0 auto 0 0;width:246px;padding:27px 18px;background:var(--navy);
color:#e6eff3;display:flex;flex-direction:column;z-index:2}.brand{display:flex;gap:12px;
align-items:center;padding:0 8px 32px;font-size:17px;letter-spacing:.03em}.brand b{font-weight:400;color:#82d3c4}
.brand small{display:block;margin-top:4px;font-size:9px;letter-spacing:.2em;color:#8ba0ad}
.brand-mark{width:40px;height:40px;border:1px solid #5f9e98;border-radius:13px;display:grid;
place-items:center;color:#8ce0ce;font-family:Georgia,serif;font-size:25px}
.workspace-label{padding:9px 11px;color:#7f98a5;font-size:9px;font-weight:700;letter-spacing:.17em}
.nav-link{display:flex;align-items:center;gap:12px;margin:3px 0;padding:11px;border-radius:8px;
color:#c1d0d7;font-size:13px}.nav-link:hover,.nav-link.selected{background:#1c4052;color:white}
.nav-link.selected{box-shadow:inset 3px 0 #54c1ac}.nav-dot{width:6px;height:6px;border-radius:50%;background:#62808e}
.nav-link.selected .nav-dot{background:#66d1b8}.sidebar-bottom{margin-top:auto;border-top:1px solid #294453;
padding:17px 6px 0}.demo-badge{display:inline-block;padding:5px 7px;border:1px solid #476272;
border-radius:4px;color:#a9c3cc;font-size:8px;letter-spacing:.11em}.user-label{display:block;
margin:15px 0 7px;font-size:12px;font-weight:600}.text-button{padding:0;border:0;background:none;
color:#a8bec8;font-size:12px;cursor:pointer}.app-main{max-width:1500px;margin-left:246px;padding:36px 4.1vw 64px}
.public-main{min-height:100vh;display:grid;place-items:center;padding:30px}.public-wrap{width:min(100%,960px)}
.hero{padding:34px 4px 27px}.eyebrow,.kicker{color:var(--teal);font-size:10px;font-weight:700;
letter-spacing:.16em;text-transform:uppercase}.hero h1{max-width:720px;margin:14px 0 10px;font-family:Georgia,serif;
font-size:clamp(34px,5vw,57px);font-weight:400;line-height:1.08;letter-spacing:-.035em}
.hero p{max-width:630px;color:var(--muted);font-size:15px;line-height:1.7}
.auth-card,.panel,.metric,.welcome-card{background:var(--paper);border:1px solid var(--line);
border-radius:11px;box-shadow:0 6px 22px #18344808}.auth-card{max-width:500px;padding:27px}
.auth-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.field{display:flex;flex-direction:column;gap:7px;margin:0 0 15px}
label{font-size:11px;font-weight:650;color:#435969}.field input,.field select,.field textarea{
width:100%;min-height:42px;border:1px solid #dce4e9;border-radius:6px;padding:9px 11px;
background:#fff;color:var(--ink);outline:none}.field textarea{min-height:82px;resize:vertical}
.field input:focus,.field select:focus,.field textarea:focus{border-color:#57aa9c;box-shadow:0 0 0 3px #57aa9c20}
.help{color:var(--muted);font-size:11px;line-height:1.55}.button{display:inline-flex;align-items:center;
justify-content:center;gap:7px;min-height:40px;padding:0 15px;border:1px solid var(--teal);
border-radius:6px;background:var(--teal);color:white;font-size:12px;font-weight:650;cursor:pointer}
.button:hover{background:var(--teal-dark)}.button.secondary{background:#fff;color:var(--ink);border-color:var(--line)}
.button.small{min-height:33px;padding:0 11px;font-size:11px}.button-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.auth-switch{margin-top:19px;color:var(--muted);font-size:12px}.auth-switch a{color:var(--teal);font-weight:650}
.topline{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:25px}
.topline h1{margin:7px 0 5px;font-family:Georgia,serif;font-weight:400;font-size:34px;letter-spacing:-.025em}
.topline p{margin:0;color:var(--muted);line-height:1.6}.eyebrow{font-size:9px}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin:20px 0}
.metric{padding:18px 18px 16px}.metric-label{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
.metric-value{margin-top:12px;font-family:Georgia,serif;font-size:26px;letter-spacing:-.03em}
.metric-note{margin-top:5px;color:#8997a2;font-size:10px}.section-head{display:flex;justify-content:space-between;
align-items:center;gap:14px;margin:30px 0 13px}.section-head h2{margin:0;font-family:Georgia,serif;
font-size:21px;font-weight:400}.panel{overflow:hidden}.table-wrap{overflow-x:auto}table{width:100%;
border-collapse:collapse;text-align:left;white-space:nowrap}th{padding:12px 16px;background:#fafcfd;
border-bottom:1px solid var(--line);color:#718090;font-size:9px;text-transform:uppercase;letter-spacing:.08em}
td{padding:14px 16px;border-bottom:1px solid #edf1f4;font-size:12px}tr:last-child td{border-bottom:0}
.primary-cell{font-weight:650}.sub-cell{display:block;margin-top:4px;color:var(--muted);font-size:10px}
.status{display:inline-block;padding:5px 8px;border-radius:20px;background:#fff5df;color:#926c22;font-size:10px}
.empty{padding:36px;text-align:center;color:var(--muted);line-height:1.7}.notice{margin:0 0 18px;padding:12px 14px;
border:1px solid #f0d9a7;border-radius:7px;background:#fff9eb;color:#755719;font-size:12px}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.form-panel{padding:23px}
.form-panel h2{margin:0 0 6px;font-family:Georgia,serif;font-size:20px;font-weight:400}
.form-panel>p{margin:0 0 20px;color:var(--muted);font-size:12px;line-height:1.55}.full{grid-column:1/-1}
.summary-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:17px;
border-bottom:1px solid var(--line);background:#fbfcfd}.summary-item span{display:block;color:var(--muted);
font-size:9px;text-transform:uppercase;letter-spacing:.08em}.summary-item strong{display:block;margin-top:8px;
font-family:Georgia,serif;font-size:19px;font-weight:400}.line-form{padding:19px;background:#fafcfd;border-bottom:1px solid var(--line)}
.line-form h3{margin:0 0 15px;font-family:Georgia,serif;font-size:17px;font-weight:400}
.line-form .field{margin-bottom:11px}.details{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:13px 0 20px}
.detail-box{padding:13px;border:1px solid var(--line);border-radius:7px;background:#fff}
.detail-box span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.08em}
.detail-box strong{display:block;margin-top:7px;font-size:13px;font-weight:600}.pill-note{padding:13px 15px;
border-left:3px solid var(--gold);background:#fffaf0;color:#725e36;font-size:11px;line-height:1.6}
.notice-footer{margin-top:24px;padding:13px 15px;border:1px solid var(--line);border-radius:7px;
color:var(--muted);font-size:10px;line-height:1.7}.link{color:var(--teal);font-weight:650}
.danger-button{border:0;background:none;color:var(--red);font-size:10px;cursor:pointer}
.cell-form{display:inline}.nowrap{white-space:nowrap}
@media(max-width:940px){.sidebar{width:205px}.app-main{margin-left:205px;padding:30px 25px}.metric-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){.sidebar{position:static;width:auto;height:auto;padding:12px 14px;display:block}
.brand{padding:0 4px 12px}.brand-mark{width:34px;height:34px}.workspace-label,.sidebar-bottom{display:none}
.sidebar nav{display:flex;gap:3px;overflow:auto}.nav-link{flex:none;margin:0;padding:9px;font-size:11px}
.nav-dot{display:none}.app-main{margin:0;padding:23px 15px 45px}.public-main{padding:18px}.hero{padding:22px 2px}
.hero h1{font-size:39px}.metric-grid{gap:9px}.metric{padding:13px}.metric-value{font-size:21px}
.form-grid,.auth-grid{grid-template-columns:1fr}.full{grid-column:auto}.summary-strip{grid-template-columns:repeat(2,1fr)}
.topline h1{font-size:29px}.topline{align-items:center}.details{grid-template-columns:1fr}}
"""


class TPMHandler(BaseHTTPRequestHandler):
    server_version = "TPMLite"
    sys_version = ""

    def log_message(self, format_string: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], format_string % args)

    def do_GET(self) -> None:
        self.dispatch("GET")

    def do_POST(self) -> None:
        self.dispatch("POST")

    def dispatch(self, method: str) -> None:
        self.session = read_session(self.headers.get("Cookie", ""))
        self.set_cookie_on_response = self.session is None
        if self.session is None:
            self.session = self.new_session()
        REQUEST_CONTEXT.csrf = str(self.session["csrf"])
        self.form: dict[str, str] = {}
        self.path = urlsplit(self.path).path
        try:
            if method == "POST":
                self.form = self.read_form()
                self.check_csrf()
            self.route(method)
        except RequestTooLarge as error:
            self.respond(
                page_layout(
                    "Request too large",
                    self.error_body(str(error)),
                    self.authenticated_user() if self.session.get("uid") else None,
                ),
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        except ValueError as error:
            self.respond(
                page_layout(
                    "Check your details",
                    self.error_body(str(error)),
                    self.authenticated_user() if self.session.get("uid") else None,
                ),
                HTTPStatus.BAD_REQUEST,
            )
        except sqlite3.Error:
            LOGGER.exception("Database operation failed while serving %s %s", method, self.path)
            self.respond(
                page_layout(
                    "Service error",
                    self.error_body(
                        "The database could not complete that request. Please try again."
                    ),
                    self.authenticated_user() if self.session.get("uid") else None,
                ),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def new_session(self, user_id: str | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        claims: dict[str, Any] = {
            "csrf": secrets.token_urlsafe(24),
            "exp": int(time.time()) + SESSION_TTL_SECONDS,
        }
        if user_id is not None and tenant_id is not None:
            claims.update({"uid": user_id, "tid": tenant_id})
        self.session = claims
        self.set_cookie_on_response = True
        return claims

    def read_form(self) -> dict[str, str]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("The submitted form could not be read.") from None
        if length < 0 or length > MAX_FORM_BYTES:
            raise RequestTooLarge("The submitted form is too large.")
        content_type = self.headers.get_content_type()
        if content_type != "application/x-www-form-urlencoded":
            raise ValueError("This form submission is not supported.")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {
            key: values[-1].strip()
            for key, values in parse_qs(raw, keep_blank_values=True).items()
        }

    def check_csrf(self) -> None:
        submitted = self.form.get("csrf", "")
        if not hmac.compare_digest(submitted, str(self.session.get("csrf", ""))):
            raise ValueError("Your session expired. Refresh the page and try again.")

    def authenticated_user(self) -> sqlite3.Row | None:
        user_id = self.session.get("uid")
        tenant_id = self.session.get("tid")
        if not user_id or not tenant_id:
            return None
        with closing(db_connect()) as connection:
            return connection.execute(
                """
                SELECT users.id, users.tenant_id, users.name, users.email,
                       tenants.name AS tenant_name
                FROM users JOIN tenants ON tenants.id = users.tenant_id
                WHERE users.id = ? AND users.tenant_id = ?
                """,
                (user_id, tenant_id),
            ).fetchone()

    def require_user(self) -> sqlite3.Row | None:
        user = self.authenticated_user()
        if user is None:
            self.redirect("/login")
        return user

    def route(self, method: str) -> None:
        if self.path == "/health" and method == "GET":
            self.respond('{"status":"ok"}', HTTPStatus.OK, content_type="application/json")
            return
        if self.path == "/":
            self.dashboard()
        elif self.path == "/login":
            if method == "POST":
                self.login()
            else:
                self.login_page()
        elif self.path == "/register":
            if method == "POST":
                self.register()
            else:
                self.register_page()
        elif self.path == "/logout" and method == "POST":
            self.logout()
        elif self.path == "/promotions":
            self.promotions_page()
        elif self.path == "/promotions/new":
            if method == "POST":
                self.create_promotion()
            else:
                self.new_promotion_page()
        elif self.path.startswith("/promotions/"):
            promotion_id = self.path.removeprefix("/promotions/")
            if method == "POST":
                self.add_promotion_item(promotion_id)
            else:
                self.promotion_detail(promotion_id)
        elif self.path.startswith("/items/") and method == "POST":
            self.delete_promotion_item(self.path.removeprefix("/items/"))
        elif self.path == "/accounts":
            if method == "POST":
                self.create_account()
            else:
                self.accounts_page()
        elif self.path == "/products":
            if method == "POST":
                self.create_product()
            else:
                self.products_page()
        else:
            self.respond(
                page_layout("Not found", self.error_body("That page does not exist.")),
                HTTPStatus.NOT_FOUND,
            )

    def respond(
        self,
        content: str,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        content_type: str = "text/html; charset=utf-8",
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
            "form-action 'self'; base-uri 'self'",
        )
        if self.set_cookie_on_response:
            secure = (
                os.environ.get("TPM_LITE_COOKIE_SECURE", "").lower() == "true"
                or self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            )
            cookie = (
                f"tpm_session={signed_session(self.session)}; Path=/; HttpOnly; "
                f"SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}"
            )
            if secure:
                cookie += "; Secure"
            self.send_header("Set-Cookie", cookie)
        for name, value in extra_headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        if self.set_cookie_on_response:
            secure = (
                os.environ.get("TPM_LITE_COOKIE_SECURE", "").lower() == "true"
                or self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            )
            cookie = (
                f"tpm_session={signed_session(self.session)}; Path=/; HttpOnly; "
                f"SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}"
            )
            if secure:
                cookie += "; Secure"
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def error_body(self, message: str) -> str:
        return (
            '<section class="auth-card"><span class="eyebrow">REQUEST NOT COMPLETED</span>'
            f"<h1>{escape(message)}</h1><p class=help>Review the information and try again.</p>"
            '<div class=button-row><a class="button secondary" href="/">Back to overview</a></div></section>'
        )

    def csrf_field(self) -> str:
        return f'<input type="hidden" name="csrf" value="{escape(self.session["csrf"])}">'

    def login_page(self, error: str = "") -> None:
        if self.session.get("uid"):
            self.redirect("/")
            return
        body = (
            '<div class=public-wrap><header class=hero><span class=eyebrow>TRADE PROMOTION MANAGEMENT</span>'
            '<h1>Plan with clarity.<br>Promote with confidence.</h1>'
            '<p>A focused workspace for promotion planning, volume phasing and estimated economics.</p></header>'
            '<section class=auth-card><h2>Welcome back</h2><p class=help>Sign in to your workspace.</p>'
            f'{"<div class=notice>" + escape(error) + "</div>" if error else ""}'
            '<form method=post action=/login>'
            f'{self.csrf_field()}<div class=field><label for=email>Work email</label>'
            '<input id=email name=email type=email autocomplete=username required maxlength=254></div>'
            '<div class=field><label for=password>Password</label>'
            '<input id=password name=password type=password autocomplete=current-password required></div>'
            '<button class=button type=submit>Sign in</button></form>'
            '<p class=auth-switch>New here? <a href=/register>Create a workspace</a></p>'
            '</section><p class=notice-footer>Synthetic demonstration workspace. Do not enter confidential company, customer, or employee data. SAP and P10 integrations are not connected.</p></div>'
        )
        self.respond(page_layout("Sign in", body), HTTPStatus.UNAUTHORIZED if error else HTTPStatus.OK)

    def register_page(self, error: str = "") -> None:
        if self.session.get("uid"):
            self.redirect("/")
            return
        body = (
            '<div class=public-wrap><header class=hero><span class=eyebrow>START A WORKSPACE</span>'
            '<h1>Make every promotion plan count.</h1>'
            '<p>Set up a private demo workspace. Your planning data is isolated from other workspaces.</p></header>'
            '<section class=auth-card><h2>Create your workspace</h2>'
            f'{"<div class=notice>" + escape(error) + "</div>" if error else ""}'
            '<form method=post action=/register>'
            f'{self.csrf_field()}<div class=field><label for=company>Workspace name</label>'
            '<input id=company name=company required maxlength=100 autocomplete=organization></div>'
            '<div class=field><label for=name>Your name</label>'
            '<input id=name name=name required maxlength=80 autocomplete=name></div>'
            '<div class=field><label for=email>Work email</label>'
            '<input id=email name=email type=email required maxlength=254 autocomplete=email></div>'
            '<div class=field><label for=password>Password</label>'
            '<input id=password name=password type=password required minlength=12 autocomplete=new-password>'
            '<span class=help>Use at least 12 characters.</span></div>'
            '<button class=button type=submit>Create workspace</button></form>'
            '<p class=auth-switch>Already have a workspace? <a href=/login>Sign in</a></p>'
            '</section><p class=notice-footer>This is a demo-grade MVP using local SQLite storage. Use synthetic data only; configure managed hosting and persistent storage before sharing sensitive business information.</p></div>'
        )
        self.respond(page_layout("Create workspace", body))

    def register(self) -> None:
        company = self.form.get("company", "").strip()
        name = self.form.get("name", "").strip()
        email = self.form.get("email", "").strip().lower()
        password = self.form.get("password", "")
        if not company or len(company) > 100:
            raise ValueError("Workspace name is required (100 characters maximum).")
        if not name or len(name) > 80:
            raise ValueError("Your name is required (80 characters maximum).")
        if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
            raise ValueError("Enter a valid email address.")
        if len(password) < 12 or len(password) > 256:
            raise ValueError("Password must be at least 12 characters.")

        tenant_id, user_id = str(uuid4()), str(uuid4())
        created_at = utc_now()
        try:
            with closing(db_connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                    (tenant_id, company, created_at),
                )
                connection.execute(
                    """
                    INSERT INTO users (id, tenant_id, name, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, tenant_id, name, email, password_digest(password), created_at),
                )
                seed_workspace(connection, tenant_id, created_at)
                connection.commit()
        except sqlite3.IntegrityError:
            self.respond(
                page_layout(
                    "Create workspace",
                    '<section class=auth-card><div class=notice>An account with that email already exists. Please sign in or use another email address.</div><a class=link href=/login>Go to sign in</a></section>',
                ),
                HTTPStatus.CONFLICT,
            )
            return

        self.session = self.new_session(user_id, tenant_id)
        REQUEST_CONTEXT.csrf = str(self.session["csrf"])
        self.redirect("/")

    def login(self) -> None:
        email = self.form.get("email", "").strip().lower()
        password = self.form.get("password", "")
        with closing(db_connect()) as connection:
            user = connection.execute(
                "SELECT id, tenant_id, password_hash FROM users WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            self.login_page("The email or password was not recognized.")
            return
        self.session = self.new_session(user["id"], user["tenant_id"])
        self.redirect("/")

    def logout(self) -> None:
        self.new_session()
        self.redirect("/login")

    def dashboard(self) -> None:
        user = self.require_user()
        if user is None:
            body = (
                '<div class=public-wrap><header class=hero><span class=eyebrow>TRADE PROMOTION MANAGEMENT</span>'
                '<h1>Plan with clarity.<br>Promote with confidence.</h1>'
                '<p>Bring account, product, volume and promotional spend planning together in one clear workspace.</p>'
                '<div class=button-row><a class=button href=/register>Create a workspace</a>'
                '<a class="button secondary" href=/login>Sign in</a></div></header>'
                '<p class=notice-footer>Synthetic demonstration app. No SAP or P10 connections. Do not enter confidential business data.</p></div>'
            )
            self.respond(page_layout("Welcome", body))
            return

        tenant_id = user["tenant_id"]
        with closing(db_connect()) as connection:
            promotions = connection.execute(
                """
                SELECT p.*, a.name AS account_name, COUNT(i.id) AS item_count
                FROM promotions p
                JOIN plan_accounts a ON a.id = p.account_id AND a.tenant_id = p.tenant_id
                LEFT JOIN promotion_items i ON i.promotion_id = p.id AND i.tenant_id = p.tenant_id
                WHERE p.tenant_id = ?
                GROUP BY p.id ORDER BY p.created_at DESC LIMIT 8
                """,
                (tenant_id,),
            ).fetchall()
            accounts_count = connection.execute(
                "SELECT COUNT(*) AS count FROM plan_accounts WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()["count"]
            products_count = connection.execute(
                "SELECT COUNT(*) AS count FROM products WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()["count"]
            all_items = connection.execute(
                """
                SELECT i.*, p.currency FROM promotion_items i
                JOIN promotions p ON p.id = i.promotion_id AND p.tenant_id = i.tenant_id
                WHERE i.tenant_id = ?
                """,
                (tenant_id,),
            ).fetchall()
            promotion_count = connection.execute(
                "SELECT COUNT(*) AS count FROM promotions WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()["count"]
        spend_by_currency: dict[str, Decimal] = {}
        for item in all_items:
            currency = item["currency"]
            spend_by_currency[currency] = spend_by_currency.get(
                currency, Decimal(0)
            ) + Decimal(str(calculate_item(item)["spend"]))
        planned_spend = (
            fmt_money(next(iter(spend_by_currency.values())), next(iter(spend_by_currency)))
            if len(spend_by_currency) == 1
            else ("Multiple currencies" if spend_by_currency else fmt_money(Decimal(0), "USD"))
        )
        spend_note = (
            "Across workspace currencies"
            if len(spend_by_currency) > 1
            else "Estimate from entered lines"
        )
        rows = "".join(
            self.promotion_row(promotion) for promotion in promotions
        ) or '<tr><td colspan=5 class=empty>No promotions yet. Create a draft to start planning.</td></tr>'
        body = (
            f'<div class=topline><div><span class=eyebrow>WORKSPACE · {escape(user["tenant_name"])}</span>'
            '<h1>Promotion overview</h1><p>Your planning work, at a glance.</p></div>'
            '<a class=button href=/promotions/new>＋ New promotion</a></div>'
            '<div class=metric-grid>'
            f'{self.metric("Draft promotions", str(promotion_count), "In this workspace")}'
            f'{self.metric("Planned spend", planned_spend, spend_note)}'
            f'{self.metric("Plan accounts", str(accounts_count), "Synthetic workspace data")}'
            f'{self.metric("OSKUs", str(products_count), "Synthetic workspace data")}'
            '</div><div class=section-head><h2>Recent promotions</h2>'
            '<a class=link href=/promotions>View all →</a></div>'
            f'<section class=panel><div class=table-wrap><table><thead><tr><th>Promotion</th><th>Plan account</th><th>Dates</th><th>Items</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
            '<p class=notice-footer>All sample accounts, OSKUs, prices and costs are synthetic. Financial values are planning estimates only—not SAP pricing, accrual, settlement, or approved financial reporting.</p>'
        )
        self.respond(page_layout("Overview", body, user, active="overview"))

    def metric(self, label: str, value: str, note: str) -> str:
        return (
            f'<article class=metric><div class=metric-label>{escape(label)}</div>'
            f'<div class=metric-value>{escape(value)}</div>'
            f'<div class=metric-note>{escape(note)}</div></article>'
        )

    def promotion_row(self, promotion: sqlite3.Row) -> str:
        return (
            f'<tr><td><a class=primary-cell href="/promotions/{escape(promotion["id"])}">'
            f'{escape(promotion["name"])}</a><span class=sub-cell>{escape(promotion["currency"])} · Created {escape(promotion["created_at"][:10])}</span></td>'
            f'<td>{escape(promotion["account_name"])}</td>'
            f'<td>{escape(promotion["start_date"])} – {escape(promotion["end_date"])}</td>'
            f'<td>{escape(promotion["item_count"])}</td>'
            f'<td><span class=status>{escape(promotion["status"])}</span></td></tr>'
        )

    def promotions_page(self) -> None:
        user = self.require_user()
        if user is None:
            return
        with closing(db_connect()) as connection:
            promotions = connection.execute(
                """
                SELECT p.*, a.name AS account_name, COUNT(i.id) AS item_count
                FROM promotions p
                JOIN plan_accounts a ON a.id = p.account_id AND a.tenant_id = p.tenant_id
                LEFT JOIN promotion_items i ON i.promotion_id = p.id AND i.tenant_id = p.tenant_id
                WHERE p.tenant_id = ?
                GROUP BY p.id ORDER BY p.created_at DESC
                """,
                (user["tenant_id"],),
            ).fetchall()
        rows = "".join(self.promotion_row(p) for p in promotions) or (
            '<tr><td colspan=5 class=empty>No draft promotions yet. '
            '<a class=link href=/promotions/new>Create your first promotion</a>.</td></tr>'
        )
        body = (
            '<div class=topline><div><span class=eyebrow>PLANNING</span><h1>Promotions</h1>'
            '<p>Create, review and refine draft promotion plans.</p></div>'
            '<a class=button href=/promotions/new>＋ New promotion</a></div>'
            '<section class=panel><div class=table-wrap><table><thead><tr><th>Promotion</th>'
            '<th>Plan account</th><th>Dates</th><th>Items</th><th>Status</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></section>'
            '<p class=notice-footer>Approval workflows and SAP/P10 transmissions are not enabled in this MVP.</p>'
        )
        self.respond(page_layout("Promotions", body, user, active="promotions"))

    def new_promotion_page(self, error: str = "") -> None:
        user = self.require_user()
        if user is None:
            return
        with closing(db_connect()) as connection:
            accounts = connection.execute(
                """
                SELECT id, code, name, currency FROM plan_accounts
                WHERE tenant_id = ? ORDER BY name
                """,
                (user["tenant_id"],),
            ).fetchall()
        if not accounts:
            self.respond(
                page_layout(
                    "New promotion",
                    '<section class=panel><div class=empty>Add a Plan Account before creating a promotion. <a class=link href=/accounts>Open Plan Accounts</a>.</div></section>',
                    user,
                    active="promotions",
                )
            )
            return
        options = "".join(
            f'<option value="{escape(a["id"])}">{escape(a["code"])} · {escape(a["name"])} ({escape(a["currency"])})</option>'
            for a in accounts
        )
        today = date.today().isoformat()
        body = (
            '<div class=topline><div><span class=eyebrow>PLANNING · NEW DRAFT</span>'
            '<h1>Create a promotion</h1><p>Start with the account and planning window. Add OSKUs next.</p></div>'
            '<a class="button secondary" href=/promotions>Cancel</a></div>'
            f'{"<div class=notice>" + escape(error) + "</div>" if error else ""}'
            '<section class="panel form-panel"><h2>Promotion details</h2>'
            '<p>Every new plan starts as a draft in your workspace.</p><form method=post action=/promotions/new>'
            f'{self.csrf_field()}<div class=field><label for=name>Promotion name</label>'
            '<input id=name name=name required maxlength=120 placeholder="e.g. Spring shelf reset"></div>'
            '<div class=field><label for=account_id>Plan Account</label>'
            f'<select id=account_id name=account_id required>{options}</select></div>'
            '<div class=form-grid><div class=field><label for=start_date>Start date</label>'
            f'<input id=start_date name=start_date type=date value="{today}" required></div>'
            '<div class=field><label for=end_date>End date</label>'
            f'<input id=end_date name=end_date type=date value="{today}" required></div></div>'
            '<div class=field><label for=description>Planning notes <span class=help>(optional)</span></label>'
            '<textarea id=description name=description maxlength=1000 placeholder="Objective or context for your team"></textarea></div>'
            '<div class=button-row><button class=button type=submit>Create draft</button>'
            '<span class=help>You can add multiple OSKU lines on the next screen.</span></div></form></section>'
            '<p class=notice-footer>Dates are planning dates only. SAP calendars, in-store timing rules and approval checks are not configured.</p>'
        )
        self.respond(page_layout("New promotion", body, user, active="promotions"))

    def create_promotion(self) -> None:
        user = self.require_user()
        if user is None:
            return
        name = self.form.get("name", "").strip()
        account_id = self.form.get("account_id", "")
        description = self.form.get("description", "").strip()
        start_date, end_date = self.form.get("start_date", ""), self.form.get("end_date", "")
        if not name or len(name) > 120:
            raise ValueError("Promotion name is required (120 characters maximum).")
        if len(description) > 1000:
            raise ValueError("Planning notes must be no longer than 1,000 characters.")
        try:
            date.fromisoformat(start_date)
            date.fromisoformat(end_date)
        except ValueError:
            raise ValueError("Enter valid start and end dates.") from None
        if end_date < start_date:
            raise ValueError("End date must be on or after the start date.")
        promotion_id = str(uuid4())
        with closing(db_connect()) as connection:
            account = connection.execute(
                "SELECT id, currency FROM plan_accounts WHERE id = ? AND tenant_id = ?",
                (account_id, user["tenant_id"]),
            ).fetchone()
            if account is None:
                raise ValueError("Select a Plan Account in your workspace.")
            connection.execute(
                """
                INSERT INTO promotions
                    (id, tenant_id, account_id, name, description, start_date, end_date,
                     currency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    promotion_id,
                    user["tenant_id"],
                    account_id,
                    name,
                    description,
                    start_date,
                    end_date,
                    account["currency"],
                    utc_now(),
                ),
            )
            connection.commit()
        self.redirect(f"/promotions/{promotion_id}")

    def promotion_detail(self, promotion_id: str) -> None:
        user = self.require_user()
        if user is None:
            return
        try:
            UUID(promotion_id)
        except ValueError:
            self.respond(
                page_layout("Not found", self.error_body("That promotion does not exist."), user),
                HTTPStatus.NOT_FOUND,
            )
            return
        with closing(db_connect()) as connection:
            promotion = connection.execute(
                """
                SELECT p.*, a.name AS account_name, a.code AS account_code
                FROM promotions p JOIN plan_accounts a
                  ON a.id = p.account_id AND a.tenant_id = p.tenant_id
                WHERE p.id = ? AND p.tenant_id = ?
                """,
                (promotion_id, user["tenant_id"]),
            ).fetchone()
            if promotion is None:
                self.respond(
                    page_layout("Not found", self.error_body("That promotion does not exist."), user),
                    HTTPStatus.NOT_FOUND,
                )
                return
            items = connection.execute(
                """
                SELECT i.*, p.sku, p.name AS product_name, p.uom
                FROM promotion_items i JOIN products p
                  ON p.id = i.product_id AND p.tenant_id = i.tenant_id
                WHERE i.promotion_id = ? AND i.tenant_id = ?
                ORDER BY i.created_at
                """,
                (promotion_id, user["tenant_id"]),
            ).fetchall()
            products = connection.execute(
                """
                SELECT id, sku, name, uom, reference_price, reference_cost
                FROM products WHERE tenant_id = ? ORDER BY name
                """,
                (user["tenant_id"],),
            ).fetchall()

        results = [(item, calculate_item(item)) for item in items]
        totals: dict[str, Decimal] = {
            key: sum((Decimal(str(result[key])) for _, result in results), Decimal(0))
            for key in (
                "gross_sales",
                "net_sales",
                "spend",
                "cost",
                "contribution",
                "incremental_contribution",
                "uplift",
            )
        }
        total_roi = (
            totals["incremental_contribution"] / totals["spend"]
            if totals["spend"] > 0
            else None
        )
        roi_text = f"{(total_roi * 100):,.1f}%" if total_roi is not None else "—"
        line_rows = "".join(self.item_row(item, result, promotion["currency"]) for item, result in results)
        if not line_rows:
            line_rows = '<tr><td colspan=9 class=empty>Add an OSKU line to see planning estimates.</td></tr>'
        product_options = "".join(
            f'<option value="{escape(p["id"])}">{escape(p["sku"])} · {escape(p["name"])} ({escape(p["uom"])})</option>'
            for p in products
        )
        add_form = (
            '<section class=line-form><h3>Add an OSKU line</h3>'
            if products
            else '<section class=line-form><h3>Add an OSKU line</h3><p class=help>No products yet. Add an OSKU in <a class=link href=/products>OSKUs</a>.</p>'
        )
        if products:
            add_form += (
                f'<form method=post action="/promotions/{escape(promotion_id)}">'
                f'{self.csrf_field()}<div class=form-grid>'
                '<div class=field><label for=product_id>OSKU</label>'
                f'<select id=product_id name=product_id required>{product_options}</select></div>'
                '<div class=field><label for=baseline_volume>Baseline volume (units)</label>'
                '<input id=baseline_volume name=baseline_volume type=number min=0 step=0.01 value=100 required></div>'
                '<div class=field><label for=planned_volume>Planned promotion volume (units)</label>'
                '<input id=planned_volume name=planned_volume type=number min=0.01 step=0.01 value=120 required></div>'
                '<div class=field><label for=regular_price>Regular price per unit</label>'
                '<input id=regular_price name=regular_price type=number min=0 step=0.01 value=10 required>'
                '<span class=help>Enter the planning price in the promotion currency.</span></div>'
                '<div class=field><label for=unit_cost>Unit cost</label>'
                '<input id=unit_cost name=unit_cost type=number min=0 step=0.01 value=5 required>'
                '<span class=help>Synthetic planning input only; confirm approved cost basis.</span></div>'
                '<div class=field><label for=spend_type>Spend mechanic</label><select id=spend_type name=spend_type>'
                '<option value=rate>Per-unit rate</option><option value=percent>Percent discount</option>'
                '<option value=lump_sum>Fixed lump sum</option></select></div>'
                '<div class=field><label for=spend_amount>Spend amount</label>'
                '<input id=spend_amount name=spend_amount type=number min=0 step=0.01 value=1 required>'
                '<span class=help>Per-unit amount, percentage, or fixed total according to the mechanic.</span></div>'
                '<div class=field><label for=spend_treatment>Spend treatment</label>'
                '<select id=spend_treatment name=spend_treatment>'
                '<option value=on_invoice>On-invoice</option><option value=off_invoice>Off-invoice</option>'
                '</select></div></div><button class=button type=submit>Add line &amp; calculate</button></form>'
            )
        add_form += "</section>"
        description = (
            f'<p>{escape(promotion["description"])}</p>' if promotion["description"] else ""
        )
        body = (
            f'<div class=topline><div><span class=eyebrow>PLANNING · {escape(promotion["status"].upper())}</span>'
            f'<h1>{escape(promotion["name"])}</h1>'
            f'<p>{escape(promotion["account_code"])} · {escape(promotion["account_name"])} · {escape(promotion["start_date"])} – {escape(promotion["end_date"])}</p>'
            f'{description}</div><a class="button secondary" href=/promotions>← Promotions</a></div>'
            f'<section class=panel><div class=summary-strip>'
            f'<div class=summary-item><span>Promotion items</span><strong>{len(items)}</strong></div>'
            f'<div class=summary-item><span>Planned spend</span><strong>{fmt_money(totals["spend"], promotion["currency"])}</strong></div>'
            f'<div class=summary-item><span>Incremental contribution</span><strong>{fmt_money(totals["incremental_contribution"], promotion["currency"])}</strong></div>'
            f'<div class=summary-item><span>Estimated ROI</span><strong>{roi_text}</strong></div>'
            f'{add_form}<div class=table-wrap><table><thead><tr>'
            '<th>OSKU</th><th>Baseline</th><th>Planned</th><th>Uplift</th><th>Landed price</th>'
            '<th>Spend</th><th>Net sales</th><th>Contribution</th><th></th></tr></thead>'
            f'<tbody>{line_rows}</tbody></table></div></section>'
            '<div class=details>'
            f'<div class=detail-box><span>Gross sales estimate</span><strong>{fmt_money(totals["gross_sales"], promotion["currency"])}</strong></div>'
            f'<div class=detail-box><span>Net sales estimate</span><strong>{fmt_money(totals["net_sales"], promotion["currency"])}</strong></div>'
            f'<div class=detail-box><span>Cost estimate</span><strong>{fmt_money(totals["cost"], promotion["currency"])}</strong></div>'
            f'<div class=detail-box><span>Planned uplift</span><strong>{fmt_quantity(totals["uplift"])} units</strong></div>'
            '</div><p class=pill-note>Planning estimates only. On-invoice discounts reduce landed price; off-invoice spend is deducted from gross sales, avoiding duplicate deduction in this estimate. Confirm Finance definitions, cost basis and rounding before business use. No accrual is calculated or posted.</p>'
        )
        self.respond(page_layout(promotion["name"], body, user, active="promotions"))

    def item_row(
        self, item: sqlite3.Row, result: dict[str, Decimal | str], currency: str
    ) -> str:
        roi = result["roi"]
        roi_label = f"{Decimal(str(roi)) * 100:,.1f}%" if roi is not None else "—"
        return (
            f'<tr><td><span class=primary-cell>{escape(item["sku"])}</span>'
            f'<span class=sub-cell>{escape(item["product_name"])}</span></td>'
            f'<td>{fmt_quantity(Decimal(item["baseline_volume"]))} {escape(item["uom"])}</td>'
            f'<td>{fmt_quantity(Decimal(item["planned_volume"]))} {escape(item["uom"])}</td>'
            f'<td>{fmt_quantity(Decimal(str(result["uplift"])))} {escape(item["uom"])}</td>'
            f'<td>{fmt_money(Decimal(str(result["landed_price"])), currency)}</td>'
            f'<td>{fmt_money(Decimal(str(result["spend"])), currency)}'
            f'<span class=sub-cell>{escape(SPEND_TREATMENTS[item["spend_treatment"]])} · {escape(SPEND_TYPES[item["spend_type"]])}</span></td>'
            f'<td>{fmt_money(Decimal(str(result["net_sales"])), currency)}</td>'
            f'<td>{fmt_money(Decimal(str(result["contribution"])), currency)}'
            f'<span class=sub-cell>ROI {roi_label}</span></td>'
            f'<td><form class=cell-form method=post action="/items/{escape(item["id"])}">'
            f'{self.csrf_field()}<button class=danger-button type=submit>Remove</button></form></td></tr>'
        )

    def add_promotion_item(self, promotion_id: str) -> None:
        user = self.require_user()
        if user is None:
            return
        try:
            UUID(promotion_id)
        except ValueError:
            self.respond(
                page_layout("Not found", self.error_body("That promotion does not exist."), user),
                HTTPStatus.NOT_FOUND,
            )
            return
        baseline = decimal_input(self.form.get("baseline_volume", ""), "baseline volume")
        planned = decimal_input(
            self.form.get("planned_volume", ""), "planned volume", minimum=Decimal("0.01")
        )
        regular_price = decimal_input(self.form.get("regular_price", ""), "regular price")
        unit_cost = decimal_input(self.form.get("unit_cost", ""), "unit cost")
        spend_type = self.form.get("spend_type", "")
        treatment = self.form.get("spend_treatment", "")
        if spend_type not in SPEND_TYPES:
            raise ValueError("Choose a supported spend mechanic.")
        if treatment not in SPEND_TREATMENTS:
            raise ValueError("Choose on-invoice or off-invoice spend treatment.")
        amount = decimal_input(self.form.get("spend_amount", ""), "spend amount")
        if spend_type == "percent" and amount > 100:
            raise ValueError("Percentage discount must be between 0 and 100.")
        if spend_type == "rate" and treatment == "on_invoice" and amount > regular_price:
            raise ValueError("On-invoice per-unit discount cannot exceed the regular price.")
        if spend_type == "percent" and treatment == "on_invoice" and amount > 100:
            raise ValueError("On-invoice discount cannot exceed the regular price.")
        if (
            spend_type == "lump_sum"
            and treatment == "on_invoice"
            and amount > regular_price * planned
        ):
            raise ValueError("On-invoice lump sum cannot exceed the planned gross sales.")
        product_id = self.form.get("product_id", "")
        with closing(db_connect()) as connection:
            promotion = connection.execute(
                "SELECT id FROM promotions WHERE id = ? AND tenant_id = ?",
                (promotion_id, user["tenant_id"]),
            ).fetchone()
            if promotion is None:
                self.respond(
                    page_layout("Not found", self.error_body("That promotion does not exist."), user),
                    HTTPStatus.NOT_FOUND,
                )
                return
            product = connection.execute(
                "SELECT id FROM products WHERE id = ? AND tenant_id = ?",
                (product_id, user["tenant_id"]),
            ).fetchone()
            if product is None:
                raise ValueError("Choose an OSKU in your workspace.")
            item_id = str(uuid4())
            try:
                connection.execute(
                    """
                    INSERT INTO promotion_items
                        (id, tenant_id, promotion_id, product_id, baseline_volume,
                         planned_volume, regular_price, unit_cost, spend_type,
                         spend_amount, spend_treatment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        user["tenant_id"],
                        promotion_id,
                        product_id,
                        str(baseline),
                        str(planned),
                        str(regular_price),
                        str(unit_cost),
                        spend_type,
                        str(amount),
                        treatment,
                        utc_now(),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                raise ValueError("This OSKU is already on the promotion.") from None
        self.redirect(f"/promotions/{promotion_id}")

    def delete_promotion_item(self, item_id: str) -> None:
        user = self.require_user()
        if user is None:
            return
        try:
            UUID(item_id)
        except ValueError:
            self.respond(
                page_layout("Not found", self.error_body("That promotion line does not exist."), user),
                HTTPStatus.NOT_FOUND,
            )
            return
        with closing(db_connect()) as connection:
            item = connection.execute(
                """
                SELECT i.id, i.promotion_id FROM promotion_items i
                JOIN promotions p ON p.id = i.promotion_id AND p.tenant_id = i.tenant_id
                WHERE i.id = ? AND i.tenant_id = ? AND p.status = 'Draft'
                """,
                (item_id, user["tenant_id"]),
            ).fetchone()
            if item is None:
                self.respond(
                    page_layout("Not found", self.error_body("That draft line does not exist."), user),
                    HTTPStatus.NOT_FOUND,
                )
                return
            connection.execute(
                "DELETE FROM promotion_items WHERE id = ? AND tenant_id = ?",
                (item_id, user["tenant_id"]),
            )
            connection.commit()
        self.redirect(f"/promotions/{item['promotion_id']}")

    def accounts_page(self) -> None:
        user = self.require_user()
        if user is None:
            return
        with closing(db_connect()) as connection:
            accounts = connection.execute(
                """
                SELECT a.*, COUNT(p.id) AS promotion_count FROM plan_accounts a
                LEFT JOIN promotions p ON p.account_id = a.id AND p.tenant_id = a.tenant_id
                WHERE a.tenant_id = ? GROUP BY a.id ORDER BY a.name
                """,
                (user["tenant_id"],),
            ).fetchall()
        rows = "".join(
            f'<tr><td class=primary-cell>{escape(account["code"])}</td>'
            f'<td>{escape(account["name"])}</td><td>{escape(account["currency"])}</td>'
            f'<td>{escape(account["promotion_count"])}</td></tr>'
            for account in accounts
        ) or '<tr><td colspan=4 class=empty>No Plan Accounts found.</td></tr>'
        body = (
            '<div class=topline><div><span class=eyebrow>REFERENCE DATA · SYNTHETIC</span>'
            '<h1>Plan Accounts</h1><p>Workspace-local demo accounts for promotion planning.</p></div></div>'
            '<div class=details><section class="panel form-panel"><h2>Add a Plan Account</h2>'
            '<p>For demonstration only. Production master data must be sourced from the approved SAP contract.</p>'
            '<form method=post action=/accounts>'
            f'{self.csrf_field()}<div class=field><label for=code>Account code</label>'
            '<input id=code name=code required maxlength=40 placeholder="e.g. ACCOUNT-03"></div>'
            '<div class=field><label for=name>Account name</label>'
            '<input id=name name=name required maxlength=100></div>'
            '<div class=field><label for=currency>Currency</label><select id=currency name=currency>'
            '<option>USD</option><option>CAD</option><option>EUR</option><option>GBP</option><option>AUD</option>'
            '</select></div><button class=button type=submit>Add Plan Account</button></form></section>'
            '<section class=panel><div class=table-wrap><table><thead><tr><th>Code</th><th>Plan Account</th>'
            '<th>Currency</th><th>Promotions</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></section></div>'
            '<p class=notice-footer>These records are editable demo data, not synchronized SAP master data.</p>'
        )
        self.respond(page_layout("Plan Accounts", body, user, active="accounts"))

    def create_account(self) -> None:
        user = self.require_user()
        if user is None:
            return
        code = self.form.get("code", "").strip()
        name = self.form.get("name", "").strip()
        currency = self.form.get("currency", "")
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("Account code must be 2–40 letters, numbers, dashes or underscores.")
        if not name or len(name) > 100:
            raise ValueError("Account name is required (100 characters maximum).")
        if currency not in {"USD", "CAD", "EUR", "GBP", "AUD"}:
            raise ValueError("Choose a supported currency.")
        with closing(db_connect()) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO plan_accounts (id, tenant_id, code, name, currency, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid4()), user["tenant_id"], code, name, currency, utc_now()),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                raise ValueError("That account code already exists in this workspace.") from None
        self.redirect("/accounts")

    def products_page(self) -> None:
        user = self.require_user()
        if user is None:
            return
        with closing(db_connect()) as connection:
            products = connection.execute(
                "SELECT * FROM products WHERE tenant_id = ? ORDER BY name",
                (user["tenant_id"],),
            ).fetchall()
        rows = "".join(
            f'<tr><td class=primary-cell>{escape(p["sku"])}</td><td>{escape(p["name"])}</td>'
            f'<td>{escape(p["uom"])}</td><td>{escape(p["reference_price"])}</td>'
            f'<td>{escape(p["reference_cost"])}</td></tr>'
            for p in products
        ) or '<tr><td colspan=5 class=empty>No OSKUs found.</td></tr>'
        body = (
            '<div class=topline><div><span class=eyebrow>REFERENCE DATA · SYNTHETIC</span>'
            '<h1>OSKUs</h1><p>Products available for planning in this workspace.</p></div></div>'
            '<div class=details><section class="panel form-panel"><h2>Add an OSKU</h2>'
            '<p>For demonstration only. Production product, price and cost records must use confirmed source contracts.</p>'
            '<form method=post action=/products>'
            f'{self.csrf_field()}<div class=field><label for=sku>OSKU code</label>'
            '<input id=sku name=sku required maxlength=40 placeholder="e.g. SKU-104"></div>'
            '<div class=field><label for=name>Product name</label>'
            '<input id=name name=name required maxlength=100></div>'
            '<div class=field><label for=uom>Unit of measure</label><select id=uom name=uom>'
            '<option>case</option><option>unit</option><option>each</option></select></div>'
            '<div class=field><label for=reference_price>Reference price</label>'
            '<input id=reference_price name=reference_price type=number min=0 step=0.01 value=10 required></div>'
            '<div class=field><label for=reference_cost>Reference cost</label>'
            '<input id=reference_cost name=reference_cost type=number min=0 step=0.01 value=5 required></div>'
            '<button class=button type=submit>Add OSKU</button></form></section>'
            '<section class=panel><div class=table-wrap><table><thead><tr><th>OSKU</th><th>Product</th>'
            '<th>UOM</th><th>Sample price</th><th>Sample cost</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></section></div>'
            '<p class=notice-footer>Sample prices and costs are synthetic values in each Plan Account currency. They are not SAP records.</p>'
        )
        self.respond(page_layout("OSKUs", body, user, active="products"))

    def create_product(self) -> None:
        user = self.require_user()
        if user is None:
            return
        sku = self.form.get("sku", "").strip()
        name = self.form.get("name", "").strip()
        uom = self.form.get("uom", "")
        if not CODE_PATTERN.fullmatch(sku):
            raise ValueError("OSKU code must be 2–40 letters, numbers, dashes or underscores.")
        if not name or len(name) > 100:
            raise ValueError("Product name is required (100 characters maximum).")
        if uom not in {"case", "unit", "each"}:
            raise ValueError("Choose a supported unit of measure.")
        reference_price = decimal_input(
            self.form.get("reference_price", ""), "reference price"
        )
        reference_cost = decimal_input(self.form.get("reference_cost", ""), "reference cost")
        with closing(db_connect()) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO products
                        (id, tenant_id, sku, name, uom, reference_price, reference_cost, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        user["tenant_id"],
                        sku,
                        name,
                        uom,
                        str(reference_price),
                        str(reference_cost),
                        utc_now(),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                raise ValueError("That OSKU code already exists in this workspace.") from None
        self.redirect("/products")


def seed_workspace(
    connection: sqlite3.Connection, tenant_id: str, created_at: str
) -> None:
    accounts = [
        ("DEMO-001", "Northstar Market", "USD"),
        ("DEMO-002", "Harbor & Pine Retail", "USD"),
    ]
    for code, name, currency in accounts:
        connection.execute(
            """
            INSERT INTO plan_accounts (id, tenant_id, code, name, currency, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), tenant_id, code, name, currency, created_at),
        )
    products = [
        ("SKU-101", "Everyday Essentials", "case", "18.00", "9.25"),
        ("SKU-204", "Bright Home Collection", "case", "24.50", "12.80"),
        ("SKU-318", "Pure Living Refill", "case", "15.75", "7.40"),
    ]
    for sku, name, uom, price, cost in products:
        connection.execute(
            """
            INSERT INTO products
                (id, tenant_id, sku, name, uom, reference_price, reference_cost, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), tenant_id, sku, name, uom, price, cost, created_at),
        )


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    initialize_database()
    hosted_host = "0.0.0.0" if IS_HOSTED else "127.0.0.1"
    host = os.environ.get("HOST", hosted_host)
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), TPMHandler)
    server.daemon_threads = True
    LOGGER.info("TPM Lite listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down TPM Lite")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()