import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DashboardOverview, PromotionSummary } from "../../services/api";
import { getDashboardOverview } from "../../services/api";
import "./dashboard.css";

type UpcomingFilter = "all" | "plan_account" | "brand" | "market" | "tactic" | "status";

function money(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

function compactMoney(amount: number, currency: string): string {
  const formatted = new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(amount);
  return `${currency} ${formatted}`;
}

function volume(amount: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(amount);
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
  }).format(new Date(`${value}T00:00:00`));
}

function elapsed(value: string): string {
  const days = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000),
  );
  if (days === 0) return "Today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

function filterHref(filter: string): string {
  return `/promotions?filter=${encodeURIComponent(filter)}`;
}

function DashboardSkeleton() {
  return (
    <Box aria-label="Loading promotion overview" role="status">
      <Skeleton width="35%" height={38} />
      <Skeleton width="55%" height={28} />
      <Box className="dashboard-kpi-grid">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton
            className="dashboard-skeleton-card"
            height={132}
            key={index}
            variant="rounded"
          />
        ))}
      </Box>
      <Skeleton className="dashboard-skeleton-panel" height={300} variant="rounded" />
      <Skeleton className="dashboard-skeleton-panel" height={280} variant="rounded" />
    </Box>
  );
}

function KpiCard({
  title,
  value,
  subtitle,
  href,
  tooltip,
  accent = false,
}: {
  title: string;
  value: string;
  subtitle: string;
  href: string;
  tooltip: string;
  accent?: boolean;
}) {
  return (
    <Tooltip arrow placement="top" title={tooltip}>
      <Card className={`dashboard-kpi-card${accent ? " is-priority" : ""}`} elevation={0}>
        <CardActionArea
          aria-label={`${title}: ${value}. ${subtitle}. Open filtered promotion worklist.`}
          className="dashboard-kpi-action"
          component={RouterLink}
          to={href}
        >
          <span className="dashboard-kpi-title">{title}</span>
          <span className="dashboard-kpi-value">{value}</span>
          <span className="dashboard-kpi-subtitle">{subtitle}</span>
          <span aria-hidden="true" className="dashboard-kpi-arrow">
            →
          </span>
        </CardActionArea>
      </Card>
    </Tooltip>
  );
}

function SectionHeading({
  title,
  action,
}: {
  title: string;
  action?: { label: string; href: string };
}) {
  return (
    <Box className="dashboard-section-heading">
      <Typography component="h2" variant="h2">
        {title}
      </Typography>
      {action && (
        <Button component={RouterLink} size="small" to={action.href} variant="text">
          {action.label}
        </Button>
      )}
    </Box>
  );
}

function PromotionFlags({ promotion }: { promotion: PromotionSummary }) {
  return (
    <Stack className="dashboard-flags" direction="row" flexWrap="wrap" spacing={0.5}>
      {promotion.starting_soon && (
        <Chip
          color="warning"
          label="Starting soon"
          size="small"
          title="Promotion starts within the next week"
        />
      )}
      {promotion.negative_contribution && (
        <Chip
          color="error"
          label="Negative contribution"
          size="small"
          title="Planned contribution is below zero"
        />
      )}
      {promotion.validation_warnings && (
        <Chip
          color="warning"
          label="Validation warning"
          size="small"
          title="Review validation messages before approval"
        />
      )}
    </Stack>
  );
}

function PendingApprovalTable({ items }: { items: PromotionSummary[] }) {
  if (items.length === 0) {
    return (
      <div className="dashboard-empty" role="status">
        <span aria-hidden="true" className="dashboard-empty-mark">
          ✓
        </span>
        <Typography component="h3" variant="h3">
          You&apos;re all caught up.
        </Typography>
        <Typography color="text.secondary">
          No promotions are waiting for your approval.
        </Typography>
      </div>
    );
  }

  return (
    <div className="dashboard-table-scroll">
      <table className="dashboard-table">
        <thead>
          <tr>
            <th scope="col">Promotion</th>
            <th scope="col">Plan Account</th>
            <th scope="col">Promotion Dates</th>
            <th scope="col">Planned Spend</th>
            <th scope="col">Planned Contribution</th>
            <th scope="col">Submitted</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <RouterLink className="dashboard-promotion-link" to={`/promotions/${item.id}`}>
                  {item.name}
                </RouterLink>
                <span className="dashboard-secondary-cell">{item.promotion_id}</span>
                <PromotionFlags promotion={item} />
              </td>
              <td>{item.plan_account}</td>
              <td>
                {dateLabel(item.start_date)} – {dateLabel(item.end_date)}
              </td>
              <td>{money(item.planned_spend, item.currency)}</td>
              <td
                className={
                  item.negative_contribution ? "dashboard-negative-value" : undefined
                }
              >
                {money(item.planned_contribution, item.currency)}
              </td>
              <td>{elapsed(item.submitted_at)}</td>
              <td>
                <Button
                  aria-label={`Review ${item.promotion_id} ${item.name}`}
                  component={RouterLink}
                  size="small"
                  to={`/promotions/${item.id}`}
                  variant="text"
                >
                  Review →
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AttentionList({ data }: { data: DashboardOverview }) {
  return (
    <Paper className="dashboard-panel dashboard-attention-panel" elevation={0}>
      <SectionHeading
        action={{ label: "View all →", href: filterHref("action-required") }}
        title="Needs your attention"
      />
      {data.attention_items.length === 0 ? (
        <div className="dashboard-empty compact" role="status">
          <Typography color="text.secondary">
            No promotions currently need intervention.
          </Typography>
        </div>
      ) : (
        <ul className="dashboard-attention-list">
          {data.attention_items.map((item) => (
            <li key={item.promotion_id}>
              <span
                aria-label={item.severity === "critical" ? "Critical" : "Warning"}
                className={`dashboard-severity-dot ${item.severity}`}
              />
              <div>
                <RouterLink
                  className="dashboard-promotion-link"
                  to={`/promotions/${item.promotion_id}`}
                >
                  {item.name}
                </RouterLink>
                <span className="dashboard-secondary-cell">{item.plan_account}</span>
                <p>{item.reason}</p>
              </div>
              <Chip
                color={item.severity === "critical" ? "error" : "warning"}
                label={item.severity === "critical" ? "Critical" : "Review"}
                size="small"
              />
            </li>
          ))}
        </ul>
      )}
    </Paper>
  );
}

function PlanningSnapshot({ data }: { data: DashboardOverview }) {
  const snapshot = data.planning_snapshot;
  return (
    <Paper className="dashboard-panel" elevation={0}>
      <SectionHeading title="Planning Snapshot" />
      <div className="dashboard-planning-metrics">
        <div>
          <span>Baseline Volume</span>
          <strong>
            {volume(snapshot.baseline_volume)} {snapshot.uom}
          </strong>
        </div>
        <div>
          <span>Promo Uplift</span>
          <strong className="dashboard-teal-value">
            +{volume(snapshot.promo_uplift)} {snapshot.uom}
          </strong>
        </div>
        <div>
          <span>Total Forecast</span>
          <strong>
            {volume(snapshot.total_forecast)} {snapshot.uom}
          </strong>
        </div>
        <div>
          <span>Promo Spend</span>
          <strong>
            {compactMoney(data.promotion_financials.planned_promo_spend, data.promotion_financials.currency)}
          </strong>
        </div>
      </div>
      <div
        aria-label="Weekly baseline volume and promotional uplift in cases"
        className="dashboard-chart"
        role="img"
      >
        <ResponsiveContainer height={258} minWidth={0} width="100%">
          <BarChart
            aria-hidden="true"
            data={snapshot.weekly_data}
            margin={{ top: 12, right: 12, left: 0, bottom: 4 }}
          >
            <CartesianGrid stroke="#e9eef0" strokeDasharray="3 3" vertical={false} />
            <XAxis axisLine={false} dataKey="week" tickLine={false} />
            <YAxis
              axisLine={false}
              tickFormatter={(value: number) => volume(value)}
              tickLine={false}
              width={48}
            />
            <ChartTooltip
              formatter={(value) => [`${Number(value).toLocaleString()} ${snapshot.uom}`]}
              labelFormatter={(label) => `Week ${label}`}
            />
            <Legend />
            <Bar
              dataKey="baseline_volume"
              fill="#168a80"
              name="Baseline Volume"
              radius={[3, 3, 0, 0]}
            />
            <Bar
              dataKey="promo_uplift"
              fill="#d5a449"
              name="Promo Uplift"
              radius={[3, 3, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="dashboard-note">
        Forecast contribution is an illustrative synthetic development estimate. Eligibility
        rules are not configured.
      </p>
    </Paper>
  );
}

function UpcomingTimeline({ data }: { data: DashboardOverview }) {
  const [filter, setFilter] = useState<UpcomingFilter>("all");
  const [filterValue, setFilterValue] = useState("all");
  const promotions = useMemo(() => {
    if (filter === "all" || filterValue === "all") return data.upcoming_items;
    return data.upcoming_items.filter((item) => item[filter] === filterValue);
  }, [data.upcoming_items, filter, filterValue]);
  const options = useMemo(
    () =>
      filter === "all"
        ? []
        : [...new Set(data.upcoming_items.map((item) => item[filter]))].sort(),
    [data.upcoming_items, filter],
  );

  return (
    <Paper className="dashboard-panel" elevation={0}>
      <SectionHeading
        action={{ label: "View all →", href: filterHref("upcoming") }}
        title="Upcoming Promotions"
      />
      <Stack className="dashboard-upcoming-filters" direction="row" spacing={1.2}>
        <FormControl size="small">
          <InputLabel id="upcoming-filter-label">Filter by</InputLabel>
          <Select
            label="Filter by"
            labelId="upcoming-filter-label"
            onChange={(event) => {
              setFilter(event.target.value as UpcomingFilter);
              setFilterValue("all");
            }}
            value={filter}
          >
            <MenuItem value="all">All promotions</MenuItem>
            <MenuItem value="plan_account">Plan Account</MenuItem>
            <MenuItem value="brand">Brand / hierarchy</MenuItem>
            <MenuItem value="market">Market</MenuItem>
            <MenuItem value="tactic">Tactic</MenuItem>
            <MenuItem value="status">Status</MenuItem>
          </Select>
        </FormControl>
        {filter !== "all" && (
          <FormControl size="small">
            <InputLabel id="upcoming-value-label">Value</InputLabel>
            <Select
              label="Value"
              labelId="upcoming-value-label"
              onChange={(event) => setFilterValue(event.target.value)}
              value={filterValue}
            >
              <MenuItem value="all">All</MenuItem>
              {options.map((option) => (
                <MenuItem key={option} value={option}>
                  {option}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
      </Stack>
      {promotions.length === 0 ? (
        <div className="dashboard-empty compact" role="status">
          <Typography color="text.secondary">
            No upcoming promotions match this filter.
          </Typography>
        </div>
      ) : (
        <ol className="dashboard-timeline">
          {promotions.map((item) => (
            <li key={item.id}>
              <time dateTime={item.start_date}>
                <strong>{dateLabel(item.start_date)}</strong>
                <span>to {dateLabel(item.end_date)}</span>
              </time>
              <span aria-hidden="true" className="dashboard-timeline-marker" />
              <div>
                <RouterLink
                  className="dashboard-promotion-link"
                  to={`/promotions/${item.id}`}
                >
                  {item.name}
                </RouterLink>
                <span className="dashboard-secondary-cell">
                  {item.plan_account} · {item.brand} · {item.tactic}
                </span>
              </div>
              <Chip
                color={item.status === "approved" ? "success" : "default"}
                label={item.status.replaceAll("_", " ")}
                size="small"
              />
            </li>
          ))}
        </ol>
      )}
    </Paper>
  );
}

function PromotionFinancialSummary({ data }: { data: DashboardOverview }) {
  const financials = data.promotion_financials;
  const items = [
    ["Gross Sales Value", money(financials.gross_sales_value, financials.currency)],
    ["Planned Promo Spend", money(financials.planned_promo_spend, financials.currency)],
    ["Net Sales Value", money(financials.net_sales_value, financials.currency)],
    ["Planned Contribution", money(financials.planned_contribution, financials.currency)],
  ];
  return (
    <Paper className="dashboard-panel" elevation={0}>
      <SectionHeading title="Promotion Financials" />
      <div className="dashboard-financial-grid">
        {items.map(([label, value]) => (
          <div className="dashboard-financial-item" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <RouterLink
        className="dashboard-negative-link"
        to={filterHref("negative-contribution")}
      >
        <span>
          <strong>{financials.negative_contribution_count}</strong> promotions with negative
          contribution
        </span>
        <span aria-hidden="true">→</span>
      </RouterLink>
      <p className="dashboard-note">
        Promotion-level planning estimates only. Customer P&amp;L and accrual calculations are
        out of scope.
      </p>
    </Paper>
  );
}

function IntegrationHealth({ data }: { data: DashboardOverview }) {
  const statuses = [
    ["SAP S/4HANA Master Data", data.integration_status.sap_master_data],
    ["SAP Promotion Interface", data.integration_status.sap_promotions],
    ["P10 Arete", data.integration_status.p10_arete],
  ] as const;
  return (
    <Paper className="dashboard-panel" elevation={0}>
      <SectionHeading title="Integration Status" />
      <ul className="dashboard-integrations">
        {statuses.map(([name, item]) => (
          <li key={name}>
            <span
              aria-label={item.status.replaceAll("_", " ")}
              className={`dashboard-integration-indicator ${item.status}`}
            />
            <div>
              <strong>{name}</strong>
              <span>{item.summary}</span>
            </div>
            <Chip
              color={
                item.status === "successful"
                  ? "success"
                  : item.status === "attention_required"
                    ? "warning"
                    : "default"
              }
              label={
                item.status === "attention_required"
                  ? "Attention required"
                  : item.status === "successful"
                    ? "Successful"
                    : "Unknown"
              }
              size="small"
            />
          </li>
        ))}
      </ul>
      <Button className="dashboard-monitor-link" component={RouterLink} to="/integrations" size="small">
        View Integration Monitor →
      </Button>
    </Paper>
  );
}

export default function Dashboard() {
  const query = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: getDashboardOverview,
  });

  if (query.isPending) return <DashboardSkeleton />;
  if (query.isError) {
    return (
      <Box className="dashboard-error">
        <Alert
          action={
            <Button color="inherit" onClick={() => void query.refetch()} size="small">
              Retry
            </Button>
          }
          severity="error"
        >
          The promotion overview could not be loaded. {query.error.message}
        </Alert>
      </Box>
    );
  }

  const data = query.data;
  const period = data.kpis.upcoming_period_weeks;

  return (
    <Box className="dashboard-page">
      <header className="dashboard-page-header">
        <div>
          <span className="dashboard-eyebrow">TPM LITE / WORKSPACE</span>
          <Typography component="h1" variant="h1">
            Promotion Overview
          </Typography>
          <Typography className="dashboard-subtitle">
            Your promotion planning workspace, at a glance.
          </Typography>
        </div>
        <Button
          component={RouterLink}
          to="/promotions/new"
          variant="contained"
        >
          + New Promotion
        </Button>
      </header>
      {data.data_source === "synthetic_development" && (
        <Alert className="dashboard-demo-alert" severity="info">
          DEMO DATA — {data.disclaimer}
        </Alert>
      )}
      <div className="dashboard-kpi-grid">
        <KpiCard
          accent
          href={filterHref("pending-approval")}
          subtitle="Waiting for your review"
          title="Pending My Approval"
          tooltip="Synthetic approval queue; identity, approval assignment, and RBAC are not configured."
          value={String(data.kpis.pending_my_approval)}
        />
        <KpiCard
          href={filterHref("action-required")}
          subtitle="Promotions needing attention"
          title="Action Required"
          tooltip="Includes illustrative validation, missing-data, negative-contribution, and interface cases."
          value={String(data.kpis.action_required)}
        />
        <KpiCard
          href={filterHref("upcoming")}
          subtitle={`Starting in the next ${period} weeks`}
          title="Upcoming Promotions"
          tooltip="Upcoming window and count are synthetic development assumptions."
          value={String(data.kpis.upcoming_promotions)}
        />
        <KpiCard
          href={filterHref("planned-spend")}
          subtitle={`All demo promotion dates · ${data.kpis.currency} · synthetic scope`}
          title="Planned Promo Spend"
          tooltip="Illustrative aggregate; permitted user scope and financial horizon are not configured."
          value={compactMoney(data.kpis.planned_promo_spend, data.kpis.currency)}
        />
      </div>
      <AttentionList data={data} />
      <Paper className="dashboard-panel dashboard-pending-panel" elevation={0}>
        <SectionHeading
          action={{
            label: "View all →",
            href: filterHref("pending-approval"),
          }}
          title="Promotions pending my approval"
        />
        <PendingApprovalTable items={data.pending_approvals} />
        <p className="dashboard-note">
          Review promotion details, OSKUs, pricing, spend, landed price, planned P&amp;L, and
          validation before any approval decision. Dashboard actions do not approve or reject.
        </p>
      </Paper>
      <div className="dashboard-two-column">
        <PlanningSnapshot data={data} />
        <UpcomingTimeline data={data} />
      </div>
      <div className="dashboard-two-column dashboard-bottom-grid">
        <PromotionFinancialSummary data={data} />
        <IntegrationHealth data={data} />
      </div>
      {data.role_configuration.source === "not_configured" && (
        <p className="dashboard-note dashboard-role-note">
          Role-based widget ordering will use the application&apos;s authenticated role
          configuration when identity and RBAC are implemented.
        </p>
      )}
    </Box>
  );
}
