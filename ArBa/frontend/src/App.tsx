import { Fragment, FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, User } from "./api";

type Market = {
  code: string;
  name: string;
  plan_mode: "VOL" | "PROMO";
  p10_sales_org: string;
  horizon_weeks: number;
};
type Customer = { id: number; market_code: string; name: string };
type Product = {
  code: string;
  description: string;
  brand: string;
  sub_brand: string;
  category: string;
};
type Tactic = { market_code: string; name: string };
type Bootstrap = {
  markets: Market[];
  customers: Customer[];
  products: Product[];
  tactics: Tactic[];
  listings: { market_code: string; customer_id: number; p09_code: string }[];
  weeks: string[];
  history_weeks: string[];
};
type BaselineProduct = Product & { baseline: number[]; actual_last_year: number[] };
type BaselineData = { weeks: string[]; products: BaselineProduct[] };
type PromotionItem = {
  product: string;
  description: string;
  baseline: number;
  total: number;
  uplift: number;
  actual: number;
};
type Promotion = {
  id: number;
  version: number;
  promo_number: string;
  market_code: string;
  customer_id: number;
  customer_name: string;
  start_date: string;
  end_date: string;
  cons_start: string;
  cons_end: string;
  tactic: string;
  status: string;
  baseline: number;
  total: number;
  uplift: number;
  actual: number;
  items: PromotionItem[];
};
type CalendarPromotion = {
  id: number;
  promo_number: string;
  start_date: string;
  end_date: string;
  tactic: string;
  status: string;
  customer_name: string;
  sub_brand: string;
  product_count: number;
};
type AccountAssignment = { market_code: string; customer_id: number };
type AdminUser = User & {
  active: boolean;
  last_login_at: string | null;
  sales_org_access: string[];
  admin_sales_org_access: string[];
};
type SalesOrg = { code: string; name: string };
type AccessData = {
  users: AdminUser[];
  assignments: (AccountAssignment & {
    user_id: number;
    customer_name: string;
  })[];
  sales_orgs: SalesOrg[];
};
type Pipeline = {
  id: string;
  name: string;
  direction: string;
  source: string;
  target: string;
  connector_type: string;
  config_json: { file_path?: string | null; [key: string]: unknown };
  enabled: boolean;
  schedule_frequency: "DAILY" | "WEEKLY" | "MONTHLY" | "QUARTERLY";
  schedule_timezone: string;
  schedule_time: string;
  schedule_weekday: number;
  schedule_month_day: number;
  schedule_quarter_month: number;
  schedule_start_date: string | null;
  schedule_end_date: string | null;
  next_run_at: string | null;
  last_run: null | { status: string; finished_at: string | null; started_at: string | null };
};
type ManagedFile = {
  id: number;
  direction: "INBOUND" | "OUTBOUND";
  category: string;
  original_name: string;
  status: string;
  uploaded_by: string;
  created_at: string;
  processed_at: string | null;
  row_count: number;
  message: string | null;
};
type Page =
  | "weekly"
  | "promotions"
  | "calendar"
  | "history"
  | "report"
  | "listing"
  | "configuration";
type ConfigTab = "access" | "customer" | "product" | "batch" | "files";

const pageNames: Record<Page, string> = {
  weekly: "Weekly Volume",
  promotions: "Promotions",
  calendar: "Promo Calendar",
  history: "Sales History",
  report: "Volume Report",
  listing: "Product Listing",
  configuration: "Configuration",
};
const configNames: Record<ConfigTab, string> = {
  access: "Access Management",
  customer: "Customer Master",
  product: "Product Master",
  batch: "Batch Job Configuration",
  files: "Files",
};
const roles = ["PLANNER", "APPROVER", "VIEWER"] as const;
const editableRoles = ["PLANNER", "APPROVER", "ADMIN", "VIEWER"] as const;
const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error. Please try again.";
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function assignmentKey(assignment: AccountAssignment): string {
  return `${assignment.market_code}|${assignment.customer_id}`;
}

function accountValues(select: HTMLSelectElement): AccountAssignment[] {
  return Array.from(select.selectedOptions, (option) => {
    const [market_code, id] = option.value.split("|");
    return { market_code, customer_id: Number(id) };
  });
}

function multiValues(select: HTMLSelectElement): string[] {
  return Array.from(select.selectedOptions, (option) => option.value);
}

async function encodeFile(file: File): Promise<string> {
  if (file.size > 10_000_000) throw new Error("The file must be no larger than 10 MB.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32_768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32_768));
  }
  return btoa(binary);
}

async function downloadApiFile(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? "/api/v1"}${path}`, {
    credentials: "include",
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the HTTP error when the response isn't JSON.
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition");
  const filename = disposition?.match(/filename="([^"]+)"/i)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState<Page>("weekly");
  const [configTab, setConfigTab] = useState<ConfigTab>("access");
  const [market, setMarket] = useState("");
  const [customerId, setCustomerId] = useState(0);
  const [revision, setRevision] = useState(0);
  const [calendarPromotionId, setCalendarPromotionId] = useState<number | null>(null);
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  const reloadBootstrap = useCallback(async () => {
    const data = await api<Bootstrap & { user: User }>("/bootstrap");
    setBootstrap(data);
    if (data.markets.length) {
      const selectedMarket = data.markets.find((item) => item.code === "DE")?.code ?? data.markets[0].code;
      setMarket(selectedMarket);
      setCustomerId(data.customers.find((item) => item.market_code === selectedMarket)?.id
        ?? data.customers[0]?.id ?? 0);
    }
  }, []);
  const refreshConfiguration = useCallback(() => {
    setRevision((value) => value + 1);
    void reloadBootstrap().catch((reason: unknown) => setError(errorText(reason)));
  }, [reloadBootstrap]);

  const enterApp = useCallback(
    async (authenticatedUser: User) => {
      setUser(authenticatedUser);
      await reloadBootstrap();
      setError("");
    },
    [reloadBootstrap],
  );

  useEffect(() => {
    let active = true;
    Promise.all([
      api<User>("/auth/me").catch(() => null),
      api<{ enabled: boolean }>("/auth/sso/status").catch(() => ({ enabled: false })),
    ])
      .then(async ([authenticatedUser, sso]) => {
        if (!active) return;
        setSsoEnabled(sso.enabled);
        if (authenticatedUser) {
          await enterApp(authenticatedUser);
          if (new URLSearchParams(window.location.search).get("sso") === "created_admin") {
            setNotice("Your account is the first ArBa account and has been made an administrator.");
          }
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(errorText(reason));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [enterApp]);

  useEffect(() => {
    setError("");
  }, [page, configTab]);

  const currentMarket = bootstrap?.markets.find((item) => item.code === market);
  const customers = useMemo(
    () => bootstrap?.customers.filter((item) => item.market_code === market) ?? [],
    [bootstrap?.customers, market],
  );

  async function authenticate(path: "/auth/login" | "/auth/signup", body: object) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ user: User; first_user_admin?: boolean }>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      await enterApp(result.user);
      if (path === "/auth/signup") {
        setNotice(result.first_user_admin
          ? "Your account is the first ArBa account and has been made an administrator."
          : "Account created. An administrator must assign your role and plan-account access.");
      }
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      setBootstrap(null);
      setPage("weekly");
      setConfigTab("access");
      setNotice("");
    }
  }

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 4500);
  }

  if (!user) {
    return (
      <LoginScreen
        busy={busy}
        error={error}
        ssoEnabled={ssoEnabled}
        onAuthenticate={authenticate}
      />
    );
  }
  if (!bootstrap) {
    return <main className="center-state">Loading your ArBa workspace…</main>;
  }
  const visibleProducts = bootstrap.products;
  const isSystemAdmin = user.role === "ADMIN";
  const isArbaAdmin = isSystemAdmin || Boolean(user.admin_sales_org_access?.length);
  if (!isArbaAdmin && bootstrap.markets.length === 0) {
    return (
      <main className="access-pending">
        <header className="topbar"><strong className="wordmark">ArBa</strong><button className="button" onClick={signOut}>Sign out</button></header>
        <section className="pending-card">
          <span className="eyebrow">ACCESS PENDING</span>
          <h1>Your account is ready</h1>
          <p>An ArBa administrator must assign your sales organization and plan accounts before planning data is available.</p>
          <button className="button primary" onClick={() => void reloadBootstrap()}>Check access again</button>
        </section>
      </main>
    );
  }

  const planningPages: Page[] = ["weekly", "promotions", "calendar", "history", "report", "listing"];
  const activePage = page;
  function navigatePlanningPage(nextPage: Page) {
    setPage(nextPage);
  }

  return (
    <div className="app-shell">
      <header className="topbar app-topbar">
        <strong className="wordmark">ArBa</strong>
        <span className="product-title">Promo Volume Predictor</span>
        <span className="topbar-spacer" />
        <span className="user-name">{user.name}</span>
        <span className="role-pill">{isArbaAdmin && !isSystemAdmin ? "ORG ADMIN" : user.role}</span>
        <button className="button" onClick={signOut}>Sign out</button>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <p className="nav-caption">PLANNING</p>
          {planningPages.map((item) => (
            <button
              className={`nav-button ${activePage === item ? "selected" : ""}`}
              key={item}
              onClick={() => navigatePlanningPage(item)}
            >
              {pageNames[item]}
            </button>
          ))}
          {isArbaAdmin && (
            <>
              <p className="nav-caption">CONFIGURATION</p>
              <button
                className={`nav-button ${page === "configuration" ? "selected" : ""}`}
                onClick={() => setPage("configuration")}
              >
                Configuration
              </button>
            </>
          )}
        </aside>
        <main className="main-content">
          {page !== "configuration" && <section className="selection-bar">
            <label>Market<select value={market} onChange={(event) => {
              const next = event.target.value;
              setMarket(next);
              const nextCustomer = bootstrap.customers.find((item) => item.market_code === next);
              if (nextCustomer) setCustomerId(nextCustomer.id);
            }}>
              {bootstrap.markets.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}
            </select></label>
            <label>Plan Account<select value={customerId} onChange={(event) => setCustomerId(Number(event.target.value))}>
              {customers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>
          </section>}
          {error && <div role="alert" className="alert error-alert">{error}<button aria-label="Dismiss" onClick={() => setError("")}>×</button></div>}
          {notice && <div role="status" className="alert success-alert">{notice}</div>}
          {page === "configuration" && isArbaAdmin ? (
            <Configuration
              key={configTab}
              activeTab={configTab}
              setActiveTab={setConfigTab}
              isSystemAdmin={isSystemAdmin}
              bootstrap={bootstrap}
              flash={flash}
              setError={setError}
              refresh={refreshConfiguration}
            />
          ) : (
            <PlanningPage
              key={`${activePage}-${market}-${customerId}-${revision}`}
              page={activePage}
              market={market}
              customerId={customerId}
              user={user}
              bootstrap={bootstrap}
              products={visibleProducts}
              flash={flash}
              setError={setError}
              refresh={refresh}
              openPromotionId={calendarPromotionId}
              onPromotionOpened={() => setCalendarPromotionId(null)}
              onOpenPromotion={(promotionId) => {
                setCalendarPromotionId(promotionId);
                setPage("promotions");
              }}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function LoginScreen(props: {
  busy: boolean;
  error: string;
  ssoEnabled: boolean;
  onAuthenticate: (path: "/auth/login" | "/auth/signup", body: object) => Promise<void>;
}) {
  const [registering, setRegistering] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const query = new URLSearchParams(window.location.search);
  const ssoError = query.get("sso_error");
  const ssoErrors: Record<string, string> = {
    cancelled: "Company SSO sign-in was cancelled.",
    authentication_failed: "Company SSO could not authenticate your account.",
    account_exists: "This email already has an ArBa account. Contact an administrator.",
    account_inactive: "This ArBa account is inactive.",
    invalid_state: "The SSO request expired. Please try again.",
  };

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void props.onAuthenticate(
      registering ? "/auth/signup" : "/auth/login",
      registering ? { name, email, password } : { email, password },
    );
  }

  return (
    <main className="login-page">
      <header className="topbar"><strong className="wordmark">ArBa</strong><span className="product-title">Promo Volume Predictor</span></header>
      <section className="login-layout">
        <div className="login-copy">
          <span className="eyebrow">EUROPEAN VOLUME PLANNING</span>
          <h1>Plan with clarity.<br />Deliver with confidence.</h1>
          <p>A single workspace for baseline planning, promotions, and weekly volume visibility across your markets.</p>
          <div className="market-chips"><span>DE</span><span>ES</span><span>PT</span><i /><span>CH</span><span>NL</span><span>AT</span><span>BE</span></div>
        </div>
        <section className="login-card">
          <span className="eyebrow">YOUR WORKSPACE</span>
          <h2>{registering ? "Create your ArBa account" : "Sign in to ArBa"}</h2>
          <p className="muted">{registering ? "Use your new account to sign in to ArBa." : "Use your ArBa account or company SSO to continue."}</p>
          {props.error && <p className="form-error" role="alert">{props.error}</p>}
          {ssoError && <p className="form-error" role="alert">{ssoErrors[ssoError] ?? "Company SSO could not complete sign-in."}</p>}
          {props.ssoEnabled && !registering && <button className="button sso-button" onClick={() => { window.location.href = "/api/v1/auth/sso/start"; }}>Sign in with company SSO</button>}
          <form onSubmit={submit}>
            {registering && <><label htmlFor="signup-name">User name</label><input autoComplete="name" id="signup-name" minLength={2} maxLength={100} onChange={(event) => setName(event.target.value)} required value={name} /></>}
            <label htmlFor="email">Email ID</label>
            <input autoComplete={registering ? "email" : "username"} id="email" onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required type="email" value={email} />
            <label htmlFor="password">Password{registering && " (at least 12 characters)"}</label>
            <input autoComplete={registering ? "new-password" : "current-password"} id="password" minLength={registering ? 12 : undefined} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} />
            <button className="button primary wide" disabled={props.busy} type="submit">{props.busy ? "Please wait…" : registering ? "Create account" : "Sign in"}</button>
          </form>
          <button className="text-button" onClick={() => setRegistering((value) => !value)}>{registering ? "Back to sign in" : "New to ArBa? Create an account"}</button>
          {registering && <p className="muted small-note">The first account created becomes the ArBa administrator. Later accounts need access assigned by an administrator.</p>}
          {!props.ssoEnabled && <p className="muted small-note">Company SSO is not configured for this instance.</p>}
        </section>
      </section>
      <footer className="login-footer"><span>ARBA PROMO VOLUME PREDICTOR</span><span>From S/4HANA to P10 Arete</span></footer>
    </main>
  );
}

function PlanningPage(props: {
  page: Page;
  market: string;
  customerId: number;
  user: User;
  bootstrap: Bootstrap;
  products: Product[];
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
  openPromotionId: number | null;
  onPromotionOpened: () => void;
  onOpenPromotion: (promotionId: number) => void;
}) {
  switch (props.page) {
    case "weekly": return <WeeklyVolume {...props} />;
    case "promotions": return <Promotions {...props} />;
    case "calendar": return <PromoCalendar {...props} />;
    case "history": return <SalesHistory {...props} />;
    case "report": return <VolumeReport {...props} />;
    case "listing": return <ProductListing {...props} />;
    default: return null;
  }
}

type PageProps = Parameters<typeof PlanningPage>[0];
function Heading({ title, subtitle, actions }: { title: string; subtitle: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="heading-actions">{actions}</div></div>;
}

function WeeklyVolume(props: PageProps) {
  const [data, setData] = useState<BaselineData | null>(null);
  const [values, setValues] = useState<Record<string, number>>({});
  const [dirty, setDirty] = useState(false);
  const baselineFileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    api<BaselineData>(`/baseline?market=${props.market}&customer_id=${props.customerId}`)
      .then((result) => {
        setData(result);
        setValues(Object.fromEntries(result.products.flatMap((product) =>
          result.weeks.map((week, index) => [`${product.code}|${week}`, product.baseline[index] ?? 0]),
        )));
      })
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.refresh, props.setError]);
  if (!data) return <p className="muted">Loading weekly volume…</p>;
  const products = data.products.filter((item) => props.products.some((product) => product.code === item.code));
  const weeks = data.weeks;
  async function save() {
    try {
      const cells = products.flatMap((product) =>
        weeks.map((week) => ({ product: product.code, week, qty_cs: values[`${product.code}|${week}`] ?? 0 })),
      );
      const result = await api<{ saved: number }>("/baseline", { method: "PUT", body: JSON.stringify({ market: props.market, customer_id: props.customerId, cells }) });
      setDirty(false);
      props.flash(`Saved ${result.saved} baseline cells`);
    } catch (error) { props.setError(errorText(error)); }
  }
  async function uploadBaseline(file: File | undefined) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      props.setError("Select an XLSX baseline workbook.");
      return;
    }
    try {
      const result = await api<{ saved: number }>("/baseline/upload", {
        method: "POST",
        body: JSON.stringify({
          market: props.market,
          customer_id: props.customerId,
          filename: file.name,
          content_base64: await encodeFile(file),
        }),
      });
      setDirty(false);
      props.flash(`Loaded ${result.saved} weekly baseline values.`);
      props.refresh();
    } catch (error) { props.setError(errorText(error)); }
    finally {
      if (baselineFileInput.current) baselineFileInput.current.value = "";
    }
  }
  async function exportBaseline() {
    try {
      await downloadApiFile(
        `/baseline/export?market=${encodeURIComponent(props.market)}&customer_id=${props.customerId}`,
        `baseline_${props.market}_${props.customerId}.xlsx`,
      );
    } catch (error) { props.setError(errorText(error)); }
  }
  const canEdit = ["PLANNER", "APPROVER", "ADMIN"].includes(props.user.role);
  return <>
    <Heading title="Weekly Volume" subtitle={`${props.market} · ${products.length} listed products · baseline cases`} actions={<>
      <button className="button" onClick={() => void exportBaseline()}>Extract Baseline XLSX</button>
      {canEdit && <>
        <input ref={baselineFileInput} accept=".xlsx" className="visually-hidden" onChange={(event) => void uploadBaseline(event.target.files?.[0])} type="file" />
        <button className="button" onClick={() => baselineFileInput.current?.click()}>Load Baseline XLSX</button>
        <button className="button primary" disabled={!dirty} onClick={() => void save()}>Save baseline</button>
      </>}
    </>} />
    <div className="table-scroll"><table className="data-table wide-table"><thead><tr><th>Product</th><th>Row</th>{data.weeks.map((week) => <th key={week}>{week}</th>)}</tr></thead><tbody>
      {products.map((product) => <Fragment key={product.code}><tr><td className="sticky-product"><b>{product.description}</b><small>{product.brand} · {product.sub_brand} · {product.code}</small></td><td>FORECAST</td>{data.weeks.map((week) => <td key={week}><input className="volume-input" disabled={!canEdit} min="0" step="1" type="number" value={values[`${product.code}|${week}`] ?? 0} onChange={(event) => { setValues((current) => ({ ...current, [`${product.code}|${week}`]: Number(event.target.value) })); setDirty(true); }} /></td>)}</tr><tr className="actual-row"><td className="sticky-product">{product.description}<small>{product.code}</small></td><td>ACTUAL LY</td>{product.actual_last_year.map((value, index) => <td key={data.weeks[index]}>{value}</td>)}</tr></Fragment>)}
    </tbody></table></div>
  </>;
}

function Promotions(props: PageProps) {
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Promotion | null>(null);
  const [selectedProducts, setSelectedProducts] = useState<string[]>([]);
  const [productToAdd, setProductToAdd] = useState("");
  const [totals, setTotals] = useState<Record<string, number>>({});
  const [baselines, setBaselines] = useState<Record<string, number> | null>(null);
  const previousBaselines = useRef<Record<string, number> | null>(null);
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [consStart, setConsStart] = useState(today());
  const [consEnd, setConsEnd] = useState(today());
  const [tactic, setTactic] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const reload = useCallback(() => {
    api<{ promotions: Promotion[] }>(`/promotions?market=${props.market}&customer_id=${props.customerId}`)
      .then((result) => setPromotions(result.promotions))
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.setError]);
  useEffect(reload, [reload, props.refresh]);
  useEffect(() => {
    setBaselines(null);
    let currentRequest = true;
    api<{ baselines: Record<string, number> }>(
      `/promotions/baseline?market=${props.market}&customer_id=${props.customerId}&start_date=${start}&end_date=${end}`,
    )
      .then((result) => { if (currentRequest) setBaselines(result.baselines); })
      .catch((error: unknown) => { if (currentRequest) props.setError(errorText(error)); });
    return () => { currentRequest = false; };
  }, [props.market, props.customerId, props.setError, start, end]);
  const listed = props.bootstrap.listings.filter((item) => item.market_code === props.market && item.customer_id === props.customerId).map((item) => item.p09_code);
  const available = props.bootstrap.products.filter((item) => listed.includes(item.code));
  const tactics = props.bootstrap.tactics.filter((item) => item.market_code === props.market);
  function baselineFor(code: string): number {
    return baselines?.[code] ?? 0;
  }
  useEffect(() => {
    if (baselines === null) return;
    const previous = previousBaselines.current;
    setTotals((current) => {
      const next = { ...current };
      for (const code of selectedProducts) {
        const baseline = baselineFor(code);
        if (next[code] === undefined) next[code] = baseline;
        else if (previous?.[code] !== undefined) {
          next[code] = baseline + Math.max(0, next[code] - previous[code]);
        }
      }
      return next;
    });
    previousBaselines.current = baselines;
  }, [selectedProducts, baselines]);
  useEffect(() => {
    if (props.openPromotionId === null || !promotions.some((promo) => promo.id === props.openPromotionId)) return;
    const promotionId = props.openPromotionId;
    setExpanded((current) => new Set(current).add(promotionId));
    window.requestAnimationFrame(() => {
      document.getElementById(`promotion-${promotionId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    props.onPromotionOpened();
  }, [props.openPromotionId, props.onPromotionOpened, promotions]);
  function startCreate() {
    setEditing(null);
    setSelectedProducts([]);
    setProductToAdd("");
    setTotals({});
    previousBaselines.current = null;
    setStart(today());
    setEnd(today());
    setConsStart(today());
    setConsEnd(today());
    setTactic("");
    setShowCreate(true);
  }
  function startEdit(promo: Promotion) {
    setEditing(promo);
    setSelectedProducts(promo.items.map((item) => item.product));
    setProductToAdd("");
    setTotals(Object.fromEntries(promo.items.map((item) => [item.product, item.total])));
    previousBaselines.current = Object.fromEntries(promo.items.map((item) => [item.product, item.baseline]));
    setStart(promo.start_date);
    setEnd(promo.end_date);
    setConsStart(promo.cons_start);
    setConsEnd(promo.cons_end);
    setTactic(promo.tactic);
    setShowCreate(true);
  }
  async function savePromo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const result = await api<{ promotion: Promotion; overlap_warnings: string[] }>("/promotions", { method: "POST", body: JSON.stringify({
        ...(editing ? { id: editing.id, version: editing.version } : {}),
        market: props.market, customer_id: props.customerId, start_date: start, end_date: end,
        cons_start: consStart, cons_end: consEnd, tactic,
        items: Object.fromEntries(selectedProducts.map((code) => [code, totals[code] ?? 0])),
      }) });
      props.flash(editing ? "Promotion changes saved" : `Promotion ${result.promotion.promo_number} created in Entry status`);
      if (result.overlap_warnings.length) props.flash(`Overlapping promotion warning: ${result.overlap_warnings.join(", ")}`);
      setShowCreate(false);
      setEditing(null);
      reload();
    } catch (error) { props.setError(errorText(error)); }
  }
  async function statusAction(id: number, action: "save" | "confirm" | "approve" | "revert") {
    try {
      await api(`/promotions/${id}/${action}`, { method: "POST" });
      const messages = {
        save: "Promotion moved to Planned",
        confirm: "Promotion sent for approval",
        approve: "Promotion approved",
        revert: "Future promotion reverted to Planned for editing",
      };
      props.flash(messages[action]);
      reload();
    } catch (error) { props.setError(errorText(error)); }
  }
  const canEdit = props.user.role === "PLANNER" || props.user.role === "APPROVER" || props.user.role === "ADMIN";
  const canApprove = props.user.role === "APPROVER" || props.user.role === "ADMIN";
  const statusLabels: Record<string, string> = {
    NEW: "Entry",
    SAVED: "Planned",
    CHANGED: "Approval Pending",
    APPROVED: "Approved",
  };
  const productsToAdd = available.filter((product) => !selectedProducts.includes(product.code));
  function addSelectedProduct() {
    if (!productToAdd || !baselines || selectedProducts.includes(productToAdd)) return;
    setSelectedProducts((current) => [...current, productToAdd]);
    setTotals((current) => ({ ...current, [productToAdd]: baselineFor(productToAdd) }));
    setProductToAdd("");
  }
  return <>
    <Heading title="Promotions" subtitle={`${props.market} · plan account ${props.customerId} · baseline is read-only; enter total cases`} actions={canEdit ? <button className="button primary" onClick={startCreate}>Create Promotion</button> : undefined} />
    {showCreate && <form className="panel form-grid" onSubmit={(event) => void savePromo(event)}>
      <div className="full-width"><h2>{editing ? `Edit ${editing.promo_number}` : "Create Promotion Entry"}</h2></div>
      <label>Start date<input required type="date" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label>End date<input required type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      <label>Consumption start<input required type="date" value={consStart} onChange={(event) => setConsStart(event.target.value)} /></label>
      <label>Consumption end<input required type="date" value={consEnd} onChange={(event) => setConsEnd(event.target.value)} /></label>
      <label>Tactic<select required value={tactic} onChange={(event) => setTactic(event.target.value)}><option value="">Select tactic</option>{tactics.map((item) => <option key={item.name}>{item.name}</option>)}</select></label>
      <div className="product-picker full-width">
        <label htmlFor="promotion-product">Add listed product</label>
        <select id="promotion-product" disabled={!baselines || !productsToAdd.length} value={productToAdd} onChange={(event) => setProductToAdd(event.target.value)}>
          <option value="">{baselines === null ? "Loading baseline…" : productsToAdd.length ? "Choose a product" : "All listed products added"}</option>
          {productsToAdd.map((product) => <option key={product.code} value={product.code}>{product.description} · {product.code}</option>)}
        </select>
        <button className="button" disabled={!productToAdd || !baselines} onClick={addSelectedProduct} type="button">Add product</button>
      </div>
      <div className="table-scroll full-width"><table className="data-table"><thead><tr><th>P09 Product</th><th>Baseline</th><th>Total Cases</th><th>Uplift</th><th /></tr></thead><tbody>
        {selectedProducts.map((code) => {
          const product = available.find((item) => item.code === code);
          if (!product) return null;
          const baseline = baselineFor(code);
          const total = totals[code] ?? baseline;
          return <tr key={code}>
            <td>{product.description}<small>{product.code}</small></td>
            <td>{baseline}</td>
            <td><input aria-label={`Total cases for ${product.description}`} disabled={baselines === null} min={baseline} step="1" type="number" value={total} onChange={(event) => setTotals((current) => ({ ...current, [code]: Number(event.target.value) }))} /></td>
            <td>{total - baseline}</td>
            <td><button aria-label={`Remove ${product.description}`} className="text-button" onClick={() => {
              setSelectedProducts((current) => current.filter((selected) => selected !== code));
              setTotals((current) => {
                const next = { ...current };
                delete next[code];
                return next;
              });
            }} type="button">Remove</button></td>
          </tr>;
        })}
        {!selectedProducts.length && <tr><td className="empty-cell" colSpan={5}>Choose listed products above to enter total cases.</td></tr>}
      </tbody></table></div>
      <div className="form-actions full-width"><button className="button primary" disabled={!selectedProducts.length} type="submit">{editing ? "Save changes" : "Create Entry"}</button><button className="button" type="button" onClick={() => { setShowCreate(false); setEditing(null); }}>Cancel</button></div>
    </form>}
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Promotion</th><th>Plan Account</th><th>Shipment</th><th>Tactic</th><th>Status</th><th>Baseline</th><th>Total</th><th>Uplift</th><th>Actions</th></tr></thead><tbody>
      {promotions.map((promo) => <Fragment key={promo.id}><tr id={`promotion-${promo.id}`}><td><button className="text-button" onClick={() => setExpanded((value) => { const next = new Set(value); next.has(promo.id) ? next.delete(promo.id) : next.add(promo.id); return next; })}>{expanded.has(promo.id) ? "−" : "+"} {promo.promo_number}</button></td><td>{promo.customer_name}</td><td>{promo.start_date} – {promo.end_date}</td><td>{promo.tactic}</td><td><span className={`status ${promo.status}`}>{statusLabels[promo.status] ?? promo.status}</span></td><td>{promo.baseline}</td><td>{promo.total}</td><td>{promo.uplift}</td><td className="action-cell">
        {canEdit && ["NEW", "SAVED"].includes(promo.status) && <button className="button" onClick={() => startEdit(promo)}>Edit</button>}
        {canEdit && promo.status === "NEW" && <button className="button primary" onClick={() => void statusAction(promo.id, "save")}>Save</button>}
        {canEdit && promo.status === "SAVED" && <button className="button" onClick={() => void statusAction(promo.id, "confirm")}>Confirm</button>}
        {canApprove && promo.status === "CHANGED" && <button className="button primary" onClick={() => void statusAction(promo.id, "approve")}>Approve</button>}
        {["PLANNER", "APPROVER", "ADMIN"].includes(props.user.role) && promo.status === "APPROVED" && promo.start_date > today() && <button className="button" onClick={() => void statusAction(promo.id, "revert")}>Revert to edit</button>}
      </td></tr>{expanded.has(promo.id) && promo.items.map((item) => <tr className="detail-row" key={`${promo.id}-${item.product}`}><td>{item.product}</td><td colSpan={2}>{item.description}</td><td colSpan={2}>Baseline {item.baseline} · Total {item.total}</td><td>{item.baseline}</td><td>{item.total}</td><td>Uplift {item.uplift}</td><td /></tr>)}</Fragment>)}
      {!promotions.length && <tr><td className="empty-cell" colSpan={9}>No promotions for this plan account.</td></tr>}
    </tbody></table></div>
  </>;
}

function isoWeekForDate(value: string): string {
  const day = new Date(`${value}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 4 - (day.getUTCDay() || 7));
  const year = day.getUTCFullYear();
  const firstThursday = new Date(Date.UTC(year, 0, 4));
  firstThursday.setUTCDate(firstThursday.getUTCDate() + 4 - (firstThursday.getUTCDay() || 7));
  const week = 1 + Math.round((day.getTime() - firstThursday.getTime()) / 604_800_000);
  return `${year}-W${String(week).padStart(2, "0")}`;
}

function PromoCalendar(props: PageProps) {
  const [items, setItems] = useState<CalendarPromotion[]>([]);
  const [weeks, setWeeks] = useState<string[]>([]);
  useEffect(() => {
    api<{ weeks: string[]; promotions: CalendarPromotion[] }>(`/calendar?market=${props.market}&customer_id=${props.customerId}`)
      .then((result) => { setItems(result.promotions); setWeeks(result.weeks); })
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.refresh, props.setError]);
  const statusLabels: Record<string, string> = { SAVED: "Planned", CHANGED: "Approval Pending", APPROVED: "Approved" };
  return <><Heading title="Promo Calendar" subtitle={`${props.market} · ${items.length} promotion and sub-brand rows`} />
    <div className="calendar-legend"><span className="calendar-status planned">Planned</span><span className="calendar-status approval-pending">Approval Pending</span><span className="calendar-status approved">Approved</span></div>
    <div className="table-scroll"><table className="data-table wide-table promo-calendar-table"><thead><tr><th>Promotion</th><th>Customer</th><th>Sub-brand</th><th>Products</th>{weeks.map((week) => <th key={week}>{week}</th>)}</tr></thead><tbody>{items.map((item, index) => {
      const firstWeek = isoWeekForDate(item.start_date);
      const lastWeek = isoWeekForDate(item.end_date);
      return <tr key={`${item.id}-${item.sub_brand}-${index}`}>
        <td><button className="text-button" onClick={() => props.onOpenPromotion(item.id)}>{item.promo_number}</button></td><td>{item.customer_name}</td><td>{item.sub_brand}</td><td>{item.product_count}</td>
        {weeks.map((week) => <td className={week >= firstWeek && week <= lastWeek ? `calendar-week ${item.status === "APPROVED" ? "approved" : item.status === "CHANGED" ? "approval-pending" : "planned"}` : ""} key={week}>{week >= firstWeek && week <= lastWeek ? <span title={`${statusLabels[item.status]} · ${item.tactic}`}>{item.tactic}</span> : null}</td>)}
      </tr>;
    })}
      {!items.length && <tr><td className="empty-cell" colSpan={weeks.length + 4}>No Planned, Approval Pending, or Approved promotions for this plan account.</td></tr>}
    </tbody></table></div>
  </>;
}

function SalesHistory(props: PageProps) {
  const [data, setData] = useState<{ weeks: string[]; products: (Product & { values: number[] })[] } | null>(null);
  useEffect(() => {
    api<{ weeks: string[]; products: (Product & { values: number[] })[] }>(`/history?market=${props.market}&customer_id=${props.customerId}`)
      .then(setData).catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.refresh, props.setError]);
  if (!data) return <p className="muted">Loading sales history…</p>;
  return <><Heading title="Sales History" subtitle={`${props.market} · actual sell-in · cases (CS)`} /><div className="table-scroll"><table className="data-table wide-table"><thead><tr><th>Product</th>{data.weeks.map((week) => <th key={week}>{week}</th>)}</tr></thead><tbody>{data.products.filter((item) => props.products.some((product) => product.code === item.code)).map((item) => <tr key={item.code}><td className="sticky-product">{item.description}<small>{item.code}</small></td>{item.values.map((value, index) => <td key={data.weeks[index]}>{value}</td>)}</tr>)}</tbody></table></div></>;
}

function VolumeReport(props: PageProps) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [months, setMonths] = useState<string[]>([]);
  useEffect(() => {
    api<{ rows: Record<string, unknown>[]; month_names: string[] }>(`/report?market=${props.market}&year=${year}&customer_id=${props.customerId}`)
      .then((result) => { setRows(result.rows); setMonths(result.month_names); })
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.refresh, props.setError, year]);
  const filtered = rows.filter((row) => props.products.some((product) => product.code === row.product));
  return <><Heading title="Volume Report" subtitle={`${props.market} · weekly volumes assigned to the month of the ISO-week Thursday`} actions={<label className="compact-label">Year<select value={year} onChange={(event) => setYear(Number(event.target.value))}>{[year - 1, year, year + 1].map((value) => <option key={value}>{value}</option>)}</select></label>} /><div className="table-scroll"><table className="data-table"><thead><tr><th>Plan Account</th><th>Product</th>{months.map((month) => <th key={month}>{month}</th>)}<th>Total</th></tr></thead><tbody>{filtered.map((row, index) => { const monthly = row.months as number[]; return <tr key={`${String(row.customer_id)}-${String(row.product)}-${index}`}><td>{String(row.customer)}</td><td>{String(row.description)}</td>{monthly.map((value, month) => <td key={month}>{value}</td>)}<td><b>{String(row.total)}</b></td></tr>; })}</tbody></table></div></>;
}

function ProductListing(props: PageProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  useEffect(() => {
    api<{ selected: string[] }>(`/listing?market=${props.market}&customer_id=${props.customerId}`)
      .then((result) => setSelected(new Set(result.selected)))
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.market, props.customerId, props.refresh, props.setError]);
  async function save() {
    try {
      const result = await api<{ saved: number; delisted_with_plans: string[] }>("/listing", {
        method: "PUT",
        body: JSON.stringify({ market: props.market, customer_id: props.customerId, products: [...selected] }),
      });
      props.flash(`Saved ${result.saved} listed products${result.delisted_with_plans.length ? `. Warning: products with future plans: ${result.delisted_with_plans.join(", ")}` : ""}`);
    } catch (error) { props.setError(errorText(error)); }
  }
  return <><Heading title="Product Listing" subtitle="Choose P09 products available for this plan account" actions={<><button className="button" onClick={() => setSelected(new Set(props.bootstrap.products.map((item) => item.code)))}>Select all</button><button className="button" onClick={() => setSelected(new Set())}>Clear all</button><button className="button primary" onClick={() => void save()}>Save listing</button></>} /><label className="inline-label">Search<input value={filter} onChange={(event) => setFilter(event.target.value)} /></label><div className="product-cards">{props.bootstrap.products.filter((item) => `${item.code} ${item.description} ${item.brand}`.toLowerCase().includes(filter.toLowerCase())).map((item) => <label className="product-choice" key={item.code}><input checked={selected.has(item.code)} type="checkbox" onChange={(event) => setSelected((current) => { const next = new Set(current); if (event.target.checked) next.add(item.code); else next.delete(item.code); return next; })} /><span><b>{item.description}</b><small>{item.brand} · {item.sub_brand} · {item.code}</small></span></label>)}</div></>;
}

function Configuration(props: {
  activeTab: ConfigTab;
  setActiveTab: (tab: ConfigTab) => void;
  isSystemAdmin: boolean;
  bootstrap: Bootstrap;
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
}) {
  const tabs: ConfigTab[] = props.isSystemAdmin
    ? ["access", "customer", "product", "batch", "files"]
    : ["access"];
  return <>
    <Heading title="Configuration" subtitle="Control access, master data, pipeline schedules, and integration files" />
    <nav className="config-tabs" aria-label="Configuration sections">
      {tabs.map((tab) => <button
        aria-current={props.activeTab === tab ? "page" : undefined}
        className={`button ${props.activeTab === tab ? "tab-active" : ""}`}
        key={tab}
        onClick={() => props.setActiveTab(tab)}
      >{configNames[tab]}</button>)}
    </nav>
    {props.activeTab === "access" && <AccessManagement {...props} />}
    {(props.activeTab === "customer" || props.activeTab === "product") &&
      <MasterDataConfig {...props} type={props.activeTab} />}
    {props.activeTab === "batch" && <BatchConfiguration {...props} />}
    {props.activeTab === "files" && <FilesConfiguration {...props} />}
  </>;
}

function AccessManagement(props: {
  bootstrap: Bootstrap;
  flash: (message: string) => void;
  setError: (message: string) => void;
  isSystemAdmin: boolean;
}) {
  const [data, setData] = useState<AccessData | null>(null);
  const [revision, setRevision] = useState(0);
  const [formRevision, setFormRevision] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    api<AccessData>("/admin/users").then((result) => {
      setData(result);
      setFormRevision((value) => value + 1);
    }).catch((error: unknown) => props.setError(errorText(error)));
  }, [props.setError, revision]);
  if (!data) return <p className="muted">Loading access management…</p>;

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const salesOrgSelect = form.elements.namedItem("sales_org_access") as HTMLSelectElement;
    const accountSelect = form.elements.namedItem("assignments") as HTMLSelectElement;
    const activeInput = form.elements.namedItem("active") as HTMLInputElement;
    setCreating(true);
    try {
      const created = await api<{
        id: number;
        email: string;
        role: string;
        first_admin_sales_orgs: string[];
      }>("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          email: values.get("email"),
          name: values.get("name"),
          role: values.get("role"),
          password: values.get("password"),
          active: activeInput.checked,
          sales_org_access: multiValues(salesOrgSelect),
          assignments: accountValues(accountSelect),
          admin_sales_org_access: multiValues(form.elements.namedItem("admin_sales_org_access") as HTMLSelectElement),
        }),
      });
      const firstOrgList = created.first_admin_sales_orgs.length
        ? ` First administrator for ${created.first_admin_sales_orgs.join(", ")}.`
        : "";
      props.flash(`Created User ID ${created.id} · ${created.email}.${firstOrgList}`);
      form.reset();
      setShowCreate(false);
      setRevision((value) => value + 1);
    } catch (error) { props.setError(errorText(error)); }
    finally { setCreating(false); }
  }

  async function saveUser(event: FormEvent<HTMLFormElement>, userId: number) {
    event.preventDefault();
    const form = event.currentTarget;
    const salesOrgSelect = form.elements.namedItem("sales_org_access") as HTMLSelectElement;
    const accountSelect = form.elements.namedItem("assignments") as HTMLSelectElement;
    const roleSelect = form.elements.namedItem("role") as HTMLSelectElement;
    const activeInput = form.elements.namedItem("active") as HTMLInputElement;
    const adminSalesOrgSelect = form.elements.namedItem("admin_sales_org_access") as HTMLSelectElement;
    try {
      const result = await api<{ first_admin_sales_orgs: string[] }>(`/admin/users/${userId}`, {
        method: "PUT",
        body: JSON.stringify({
          role: roleSelect.value,
          active: activeInput.checked,
          sales_org_access: multiValues(salesOrgSelect),
          assignments: accountValues(accountSelect),
          admin_sales_org_access: multiValues(adminSalesOrgSelect),
        }),
      });
      const firstOrgMessage = result.first_admin_sales_orgs.length
        ? ` First administrator for ${result.first_admin_sales_orgs.join(", ")}.`
        : "";
      props.flash(`Access updated for User ID ${userId}.${firstOrgMessage}`);
      setRevision((value) => value + 1);
    } catch (error) { props.setError(errorText(error)); }
  }

  return <section className="config-section">
    <div className="panel">
      <div className="panel-heading"><div><h2>Create User ID</h2><p>Create a user and assign role, organization, and plan-account access.</p></div><div className="action-row"><span className="count-pill">{data.users.length} users</span><button className="button primary" onClick={() => setShowCreate(true)}>Create User</button></div></div>
    </div>
    {showCreate && <div className="modal-backdrop" role="presentation">
      <section aria-labelledby="create-user-title" aria-modal="true" className="panel create-user-modal" role="dialog">
        <div className="panel-heading"><div><h2 id="create-user-title">Create User</h2><p>Choose access. Use Ctrl/Cmd to select or deselect multiple values.</p></div><button aria-label="Close" className="button" onClick={() => setShowCreate(false)} type="button">Close</button></div>
        <form className="config-form" onSubmit={(event) => void createUser(event)}>
          <label>Email ID<input autoComplete="email" maxLength={254} name="email" required type="email" /></label>
          <label>User Name<input maxLength={100} minLength={2} name="name" required /></label>
          <label>ArBa Role<select defaultValue="PLANNER" name="role">{roles.map((role) => <option key={role}>{role}</option>)}</select></label>
          <label>Initial password<input autoComplete="new-password" minLength={12} name="password" required type="password" /></label>
          <label>Sales Organization Access<select multiple name="sales_org_access" required size={4}>{data.sales_orgs.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label>
          <label>ArBa Administrator Access<select multiple name="admin_sales_org_access" size={4}>{data.sales_orgs.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select><small>Must also be selected under Sales Organization Access.</small></label>
          <label>Plan Account Access<select multiple name="assignments" size={4}>{props.bootstrap.customers.map((item) => <option key={item.id} value={assignmentKey({ market_code: item.market_code, customer_id: item.id })}>{item.market_code} · {item.name}</option>)}</select><small>Accounts must belong to the selected sales organizations.</small></label>
          <label className="active-control"><input defaultChecked name="active" type="checkbox" /> User Active</label>
          <div className="form-actions"><button className="button primary" disabled={creating} type="submit">{creating ? "Creating…" : "Create User"}</button><button className="button" onClick={() => setShowCreate(false)} type="button">Cancel</button></div>
        </form>
      </section>
    </div>}
    <div className="panel">
      <div className="panel-heading"><div><h2>Access Management</h2><p>Inactive users are automatically deactivated after 30 days without a successful sign-in.</p></div></div>
      <div className="user-access-list">
        {data.users.map((user) => {
          const accountSet = new Set(data.assignments.filter((item) => item.user_id === user.id).map(assignmentKey));
          return <form className="user-access-row" key={`${user.id}-${formRevision}`} onSubmit={(event) => void saveUser(event, user.id)}>
            <div className="user-identity"><b>User ID {user.id}</b><span>{user.email}</span><small>{user.name}</small><span className={`status ${user.active ? "ACTIVE" : "INACTIVE"}`}>{user.active ? "Active" : "Inactive"}</span><small>Last login: {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : "Never"}</small></div>
            <label>ArBa Role<select defaultValue={user.role} name="role">{editableRoles.map((role) => <option key={role}>{role}</option>)}</select></label>
            <label>Sales Organization Access<select defaultValue={user.sales_org_access} multiple name="sales_org_access" size={3}>{data.sales_orgs.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label>
            <label>ArBa Administrator Access<select defaultValue={user.admin_sales_org_access} multiple name="admin_sales_org_access" size={3}>{data.sales_orgs.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label>
            <label>Plan Account Access<select defaultValue={[...accountSet]} multiple name="assignments" size={3}>{props.bootstrap.customers.map((item) => <option key={item.id} value={assignmentKey({ market_code: item.market_code, customer_id: item.id })}>{item.market_code} · {item.name}</option>)}</select></label>
            <label className="active-control"><input defaultChecked={user.active} name="active" type="checkbox" /> Active</label>
            <button className="button" type="submit">Save access</button>
          </form>;
        })}
      </div>
    </div>
  </section>;
}

function MasterDataConfig(props: {
  type: "customer" | "product";
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [queued, setQueued] = useState<{ id: number; filename: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const customerMode = props.type === "customer";
  const title = customerMode ? "Customer Master" : "Product Master";
  const columns = customerMode
    ? ["Market Code or Sales Organization", "Plan Account Code L04", "Plan Account Name", "Parent L03"]
    : ["Product P09", "Product Description", "Brand", "Sub-brand", "Category", "Material Number", "Material Description (optional)", "Split Share (optional)"];

  async function upload() {
    if (!file) return props.setError("Select a CSV or XLSX extract first.");
    setBusy(true);
    try {
      const result = await api<{ id: number; filename: string; status: string; queue_folder: string }>(
        `/admin/master-data/${props.type}/upload`,
        { method: "POST", body: JSON.stringify({ filename: file.name, content_base64: await encodeFile(file) }) },
      );
      setQueued({ id: result.id, filename: result.filename });
      props.flash(`${result.filename} is in ${result.queue_folder}.`);
      props.refresh();
    } catch (error) { props.setError(errorText(error)); }
    finally { setBusy(false); }
  }

  async function process() {
    if (!queued) return;
    setBusy(true);
    try {
      const result = await api<{ rows: number }>(`/admin/files/${queued.id}/process`, { method: "POST" });
      props.flash(`${title} loaded: ${result.rows} rows processed.`);
      setQueued(null);
      setFile(null);
      props.refresh();
    } catch (error) { props.setError(errorText(error)); }
    finally { setBusy(false); }
  }

  return <section className="panel master-panel">
    <span className="eyebrow">SAP INBOUND</span>
    <h2>Load {title} extract</h2>
    <p>Upload a CSV or XLSX master-data extract. Files are staged in <b>Inbound Queue</b>; process performs validation and applies the entire extract atomically. Successfully processed files move to <b>Inbound Processed</b>.</p>
    <div className="required-fields"><b>Required columns</b><span>{columns.join(" · ")}</span></div>
    <label className="file-picker">Choose SAP extract<input accept=".csv,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} type="file" /></label>
    {file && <p className="selected-file">{file.name} · {(file.size / 1024).toFixed(1)} KB</p>}
    <button className="button primary" disabled={busy || !file} onClick={() => void upload()}>{busy ? "Uploading…" : "Load to Inbound Queue"}</button>
    {queued && <div className="queue-confirm"><span>{queued.filename} is queued as file #{queued.id}.</span><button className="button primary" disabled={busy} onClick={() => void process()}>Validate and consume</button></div>}
  </section>;
}

function BatchConfiguration(props: {
  flash: (message: string) => void;
  setError: (message: string) => void;
}) {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [runs, setRuns] = useState<Record<string, Record<string, unknown>[]>>({});
  const [revision, setRevision] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [dryRun, setDryRun] = useState(true);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    api<{ pipelines: Pipeline[] }>("/admin/pipelines").then((result) => setPipelines(result.pipelines))
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.setError, revision]);
  function update(id: string, changes: Partial<Pipeline>) {
    setPipelines((current) => current.map((item) => item.id === id ? { ...item, ...changes } : item));
  }
  async function save(pipeline: Pipeline) {
    try {
      await api(`/admin/pipelines/${pipeline.id}`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: pipeline.enabled,
          schedule_frequency: pipeline.schedule_frequency,
          schedule_timezone: pipeline.schedule_timezone,
          schedule_time: pipeline.schedule_time,
          schedule_weekday: pipeline.schedule_weekday,
          schedule_month_day: pipeline.schedule_month_day,
          schedule_quarter_month: pipeline.schedule_quarter_month,
          schedule_start_date: pipeline.schedule_start_date || null,
          schedule_end_date: pipeline.schedule_end_date || null,
          file_path: pipeline.config_json.file_path ?? "",
        }),
      });
      props.flash(`Saved schedule for ${pipeline.id}`);
      setRevision((value) => value + 1);
    } catch (error) { props.setError(errorText(error)); }
  }
  async function createPipeline(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setCreating(true);
    try {
      const result = await api<{ id: string }>("/admin/pipelines", {
        method: "POST",
        body: JSON.stringify({
          name: values.get("name"),
          direction: values.get("direction"),
          source: values.get("source"),
          target: values.get("target"),
          connector_type: values.get("connector_type"),
          file_path: values.get("file_path"),
          enabled: (form.elements.namedItem("enabled") as HTMLInputElement).checked,
          schedule_frequency: values.get("schedule_frequency"),
          schedule_timezone: values.get("schedule_timezone"),
          schedule_time: values.get("schedule_time"),
          schedule_weekday: Number(values.get("schedule_weekday")),
          schedule_month_day: Number(values.get("schedule_month_day")),
          schedule_quarter_month: Number(values.get("schedule_quarter_month")),
          schedule_start_date: values.get("schedule_start_date") || null,
          schedule_end_date: values.get("schedule_end_date") || null,
        }),
      });
      props.flash(`Created pipeline ${result.id}`);
      setShowCreate(false);
      setRevision((value) => value + 1);
    } catch (error) { props.setError(errorText(error)); }
    finally { setCreating(false); }
  }
  async function runNow(id: string) {
    try {
      const result = await api<{ run_id: number; status: string; message: string }>(`/admin/pipelines/${id}/run?dry_run=${dryRun}`, { method: "POST" });
      props.flash(`Run #${result.run_id}: ${result.status} · ${result.message}`);
      setRevision((value) => value + 1);
    } catch (error) { props.setError(errorText(error)); }
  }
  async function showRuns(id: string) {
    try {
      const result = await api<{ runs: Record<string, unknown>[] }>(`/admin/pipelines/${id}/runs`);
      setRuns((current) => ({ ...current, [id]: result.runs }));
    } catch (error) { props.setError(errorText(error)); }
  }
  return <section className="config-section">
    <div className="panel-heading"><div><h2>Batch Job Configuration</h2><p>Create, schedule, enable, and manually run inbound or outbound pipelines.</p></div><button className="button primary" onClick={() => setShowCreate((value) => !value)}>{showCreate ? "Close" : "Create Pipeline"}</button></div>
    <div className="schedule-explainer"><b>Pipeline schedules</b><span>Choose the local timezone and run time. Monthly and quarterly jobs use the selected calendar date; the last day is used when a month is shorter. Start/end dates limit the period during which the job runs.</span></div>
    {showCreate && <form className="panel" onSubmit={(event) => void createPipeline(event)}>
      <div className="panel-heading"><div><h2>New pipeline</h2><p>File locations are relative to the ArBa Files folder. SAP OData, SFTP, and REST connectors require their corresponding integration configuration.</p></div></div>
      <div className="schedule-grid">
        <label>Pipeline name<input maxLength={120} minLength={2} name="name" required /></label>
        <label>Direction<select name="direction"><option value="INBOUND">INBOUND · consume into ArBa</option><option value="OUTBOUND">OUTBOUND · send from ArBa</option></select></label>
        <label>Source<input defaultValue="SAP S/4HANA" name="source" required /></label>
        <label>Target<input defaultValue="ArBa" name="target" required /></label>
        <label>Connector<select name="connector_type">{["FileConnector", "MockSapConnector", "MockP10Connector", "SapOdataConnector", "SftpConnector", "RestConnector"].map((connector) => <option key={connector}>{connector}</option>)}</select></label>
        <label>File location<input name="file_path" placeholder="Inbound Queue/file.csv or Outbound/file.csv" /></label>
        <label>Frequency<select defaultValue="DAILY" name="schedule_frequency">{["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"].map((frequency) => <option key={frequency}>{frequency}</option>)}</select></label>
        <label>Timezone (IANA)<input defaultValue="UTC" name="schedule_timezone" required /></label>
        <label>Run time<input defaultValue="02:00" name="schedule_time" type="time" required /></label>
        <label>Weekday<select defaultValue="1" name="schedule_weekday">{weekdays.map((day, index) => <option key={day} value={index}>{day}</option>)}</select></label>
        <label>Day of month<input defaultValue="1" max="31" min="1" name="schedule_month_day" type="number" /></label>
        <label>Month of quarter<select defaultValue="1" name="schedule_quarter_month"><option value="1">First month</option><option value="2">Second month</option><option value="3">Third month</option></select></label>
        <label>Start date<input name="schedule_start_date" type="date" /></label>
        <label>End date<input name="schedule_end_date" type="date" /></label>
        <label className="toggle-label"><input name="enabled" type="checkbox" /> Enabled</label>
      </div>
      <div className="action-row"><button className="button primary" disabled={creating} type="submit">{creating ? "Creating…" : "Create Pipeline"}</button><button className="button" onClick={() => setShowCreate(false)} type="button">Cancel</button></div>
    </form>}
    <label className="inline-label dry-run-toggle"><input checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} type="checkbox" /> Dry run (preview only)</label>
    {pipelines.map((pipeline) => <article className="panel pipeline-card" key={pipeline.id}>
      <div className="panel-heading"><div><h2>{pipeline.id} · {pipeline.name}</h2><p>{pipeline.source} → {pipeline.target} · {pipeline.connector_type}</p></div><label className="toggle-label"><input checked={pipeline.enabled} onChange={(event) => update(pipeline.id, { enabled: event.target.checked })} type="checkbox" /> Enabled</label></div>
      <div className="schedule-grid">
        <label>Frequency<select value={pipeline.schedule_frequency} onChange={(event) => update(pipeline.id, { schedule_frequency: event.target.value as Pipeline["schedule_frequency"] })}>{["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"].map((frequency) => <option key={frequency}>{frequency}</option>)}</select></label>
        <label>Timezone (IANA)<input value={pipeline.schedule_timezone} onChange={(event) => update(pipeline.id, { schedule_timezone: event.target.value })} placeholder="Europe/Berlin" /></label>
        <label>Run time<input type="time" value={pipeline.schedule_time} onChange={(event) => update(pipeline.id, { schedule_time: event.target.value })} /></label>
        <label>Weekday<select value={pipeline.schedule_weekday} onChange={(event) => update(pipeline.id, { schedule_weekday: Number(event.target.value) })}>{weekdays.map((day, index) => <option key={day} value={index}>{day}</option>)}</select></label>
        <label>Day of month<input max="31" min="1" type="number" value={pipeline.schedule_month_day} onChange={(event) => update(pipeline.id, { schedule_month_day: Number(event.target.value) })} /></label>
        <label>Month of quarter<select value={pipeline.schedule_quarter_month} onChange={(event) => update(pipeline.id, { schedule_quarter_month: Number(event.target.value) })}><option value="1">First month</option><option value="2">Second month</option><option value="3">Third month</option></select></label>
        <label>Start date<input type="date" value={pipeline.schedule_start_date ?? ""} onChange={(event) => update(pipeline.id, { schedule_start_date: event.target.value || null })} /></label>
        <label>End date<input type="date" value={pipeline.schedule_end_date ?? ""} onChange={(event) => update(pipeline.id, { schedule_end_date: event.target.value || null })} /></label>
        <label>File location (relative to ArBa Files)<input value={pipeline.config_json?.file_path ?? ""} onChange={(event) => update(pipeline.id, { config_json: { ...pipeline.config_json, file_path: event.target.value } })} placeholder="Inbound Queue/file.csv or Outbound/file.csv" /></label>
      </div>
      <p className="schedule-status">Next run: {pipeline.next_run_at ? new Date(pipeline.next_run_at).toLocaleString() : "Not scheduled"} · Last run: {pipeline.last_run?.finished_at ?? "Never"}</p>
      <div className="action-row"><button className="button primary" onClick={() => void save(pipeline)}>Save pipeline</button><button className="button" onClick={() => void runNow(pipeline.id)}>{dryRun ? "Run now (dry run)" : "Run now"}</button><button className="button" onClick={() => void showRuns(pipeline.id)}>Run history</button></div>
      {runs[pipeline.id] && <div className="run-history">{runs[pipeline.id].map((run, index) => <p key={String(run.id ?? index)}>Run #{String(run.id)} · {String(run.trigger)} · {String(run.status)} · {String(run.message ?? "")}</p>)}</div>}
    </article>)}
  </section>;
}

function FilesConfiguration(props: {
  flash: (message: string) => void;
  setError: (message: string) => void;
}) {
  const [files, setFiles] = useState<ManagedFile[]>([]);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    api<{ files: ManagedFile[] }>("/admin/files").then((result) => setFiles(result.files))
      .catch((error: unknown) => props.setError(errorText(error)));
  }, [props.setError, revision]);
  async function process(id: number) {
    try {
      const result = await api<{ rows: number }>(`/admin/files/${id}/process`, { method: "POST" });
      setRevision((value) => value + 1);
      props.flash(`Processed ${result.rows} master rows.`);
    } catch (error) { props.setError(errorText(error)); }
  }
  return <section className="panel">
    <div className="panel-heading"><div><h2>Inbound and outbound files</h2><p>Queued inbound files are in the Inbound Queue folder. Successfully consumed files appear in Inbound Processed. P10 exports are kept under Outbound.</p></div><button className="button" onClick={() => setRevision((value) => value + 1)}>Refresh</button></div>
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Direction</th><th>Type</th><th>File</th><th>Status</th><th>Folder</th><th>Rows</th><th>Uploaded by</th><th>Created</th><th>Message</th><th>Actions</th></tr></thead><tbody>
      {files.map((file) => <tr key={file.id}><td>{file.direction}</td><td>{file.category}</td><td>{file.original_name}</td><td><span className={`status ${file.status}`}>{file.status}</span></td><td>{file.direction === "OUTBOUND" ? "Outbound" : file.status === "PROCESSED" ? "Inbound Processed" : "Inbound Queue"}</td><td>{file.row_count}</td><td>{file.uploaded_by}</td><td>{new Date(file.created_at).toLocaleString()}</td><td>{file.message}</td><td>{file.direction === "INBOUND" && ["QUEUED", "FAILED"].includes(file.status) && <button className="button primary" onClick={() => void process(file.id)}>Process</button>} <a className="button link-button" href={`/api/v1/admin/files/${file.id}/download`}>Download</a></td></tr>)}
      {!files.length && <tr><td className="empty-cell" colSpan={10}>No inbound or outbound files have been recorded.</td></tr>}
    </tbody></table></div>
  </section>;
}
