import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Stack,
  Typography,
} from "@mui/material";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";
import {
  getDashboardOverview,
  getDashboardWorklist,
  getPromotionDetail,
} from "../../services/api";
import type { DashboardFilter, PromotionSummary } from "../../services/api";

const FILTER_LABELS: Record<DashboardFilter, string> = {
  all: "All promotions",
  "pending-approval": "Pending my approval",
  "action-required": "Action required",
  upcoming: "Upcoming promotions",
  "negative-contribution": "Negative contribution",
  "planned-spend": "Planned promo spend",
};

function formatMoney(value: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(`${value}T00:00:00`));
}

function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="dashboard-page-header">
      <div>
        <span className="dashboard-eyebrow">{eyebrow}</span>
        <Typography component="h1" variant="h1">
          {title}
        </Typography>
        <Typography className="dashboard-subtitle">{description}</Typography>
      </div>
      <Button component={RouterLink} to="/" variant="outlined">
        ← Overview
      </Button>
    </header>
  );
}

function LoadingPanel() {
  return (
    <Box aria-label="Loading promotion data" role="status">
      <Skeleton height={42} width="35%" />
      <Skeleton height={320} variant="rounded" />
    </Box>
  );
}

function ErrorPanel({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <Alert
      action={
        <Button color="inherit" onClick={retry} size="small">
          Retry
        </Button>
      }
      severity="error"
    >
      Promotion data could not be loaded. {message}
    </Alert>
  );
}

function WorklistTable({ items }: { items: PromotionSummary[] }) {
  if (!items.length) {
    return (
      <div className="dashboard-empty" role="status">
        <Typography component="h2" variant="h2">
          No promotions match this filter.
        </Typography>
        <Typography color="text.secondary">
          Try another worklist filter or return to the overview.
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
            <th scope="col">Dates</th>
            <th scope="col">Planned Spend</th>
            <th scope="col">Planned Contribution</th>
            <th scope="col">Status</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {items.map((promotion) => (
            <tr key={promotion.id}>
              <td>
                <RouterLink
                  className="dashboard-promotion-link"
                  to={`/promotions/${promotion.id}`}
                >
                  {promotion.name}
                </RouterLink>
                <span className="dashboard-secondary-cell">{promotion.promotion_id}</span>
              </td>
              <td>{promotion.plan_account}</td>
              <td>
                {formatDate(promotion.start_date)} – {formatDate(promotion.end_date)}
              </td>
              <td>{formatMoney(promotion.planned_spend, promotion.currency)}</td>
              <td className={promotion.negative_contribution ? "dashboard-negative-value" : ""}>
                {formatMoney(promotion.planned_contribution, promotion.currency)}
              </td>
              <td>
                <Chip
                  color={promotion.status === "approved" ? "success" : "default"}
                  label={promotion.status.replaceAll("_", " ")}
                  size="small"
                />
              </td>
              <td>
                <Button
                  component={RouterLink}
                  size="small"
                  to={`/promotions/${promotion.id}`}
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

export function PromotionWorklistPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawFilter = searchParams.get("filter") ?? "all";
  const filter: DashboardFilter = rawFilter in FILTER_LABELS
    ? rawFilter as DashboardFilter
    : "all";
  const query = useQuery({
    queryKey: ["dashboard", "worklist", filter],
    queryFn: () => getDashboardWorklist(filter),
  });

  return (
    <Box className="dashboard-page">
      <PageHeader
        description="Review and prioritize promotion plans in your workspace."
        eyebrow="TPM LITE / WORKSPACE"
        title="Promotion Worklist"
      />
      <Paper className="dashboard-panel dashboard-worklist-panel" elevation={0}>
        <Stack className="dashboard-worklist-toolbar" direction="row" justifyContent="space-between">
          <div>
            <Typography component="h2" variant="h2">
              {FILTER_LABELS[filter]}
            </Typography>
            <Typography color="text.secondary" variant="body2">
              Synthetic development data. Approval actions are not enabled.
            </Typography>
          </div>
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="worklist-filter-label">Filter</InputLabel>
            <Select
              label="Filter"
              labelId="worklist-filter-label"
              onChange={(event) => setSearchParams({ filter: event.target.value })}
              value={filter}
            >
              {Object.entries(FILTER_LABELS).map(([value, label]) => (
                <MenuItem key={value} value={value}>
                  {label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
        {query.isPending ? (
          <LoadingPanel />
        ) : query.isError ? (
          <ErrorPanel message={query.error.message} retry={() => void query.refetch()} />
        ) : (
          <WorklistTable items={query.data} />
        )}
      </Paper>
    </Box>
  );
}

export function PromotionReviewPage() {
  const { promotionId = "" } = useParams();
  const query = useQuery({
    queryKey: ["promotion", promotionId],
    queryFn: () => getPromotionDetail(promotionId),
  });

  if (query.isPending) return <LoadingPanel />;
  if (query.isError) {
    return (
      <Box className="dashboard-page">
        <PageHeader
          description="Inspect the promotion planning details."
          eyebrow="TPM LITE / REVIEW"
          title="Promotion Review"
        />
        <ErrorPanel message={query.error.message} retry={() => void query.refetch()} />
      </Box>
    );
  }
  const promotion = query.data;
  return (
    <Box className="dashboard-page">
      <PageHeader
        description={`${promotion.promotion_id} · ${promotion.plan_account} · ${formatDate(promotion.start_date)} – ${formatDate(promotion.end_date)}`}
        eyebrow="TPM LITE / REVIEW"
        title={promotion.name}
      />
      <Alert severity="info" sx={{ mb: 2 }}>
        Synthetic review example. Approval actions are not available; no business decision
        has been recorded.
      </Alert>
      <Paper className="dashboard-panel" elevation={0}>
        <Typography component="h2" variant="h2">
          Promotion details
        </Typography>
        <Typography className="dashboard-review-description">
          {promotion.description}
        </Typography>
        <div className="dashboard-financial-grid">
          <div className="dashboard-financial-item">
            <span>Planned Spend</span>
            <strong>{formatMoney(promotion.planned_spend, promotion.currency)}</strong>
          </div>
          <div className="dashboard-financial-item">
            <span>Gross Sales</span>
            <strong>{formatMoney(promotion.gross_sales_value, promotion.currency)}</strong>
          </div>
          <div className="dashboard-financial-item">
            <span>Net Sales</span>
            <strong>{formatMoney(promotion.net_sales_value, promotion.currency)}</strong>
          </div>
          <div className="dashboard-financial-item">
            <span>Planned Contribution</span>
            <strong className={promotion.negative_contribution ? "dashboard-negative-value" : ""}>
              {formatMoney(promotion.planned_contribution, promotion.currency)}
            </strong>
          </div>
        </div>
        {promotion.validation_messages.length > 0 && (
          <Alert severity="warning" sx={{ my: 2 }}>
            <strong>Validation</strong>
            <ul>
              {promotion.validation_messages.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </Alert>
        )}
        <Typography component="h3" sx={{ mt: 3, mb: 1 }} variant="h3">
          OSKUs, pricing and spend
        </Typography>
        <div className="dashboard-table-scroll">
          <table className="dashboard-table">
            <thead>
              <tr>
                <th scope="col">OSKU</th>
                <th scope="col">Volumes</th>
                <th scope="col">Regular Price</th>
                <th scope="col">Spend Mechanic</th>
                <th scope="col">Landed Price</th>
                <th scope="col">Spend</th>
                <th scope="col">Contribution</th>
              </tr>
            </thead>
            <tbody>
              {promotion.items.map((item) => (
                <tr key={item.osku}>
                  <td>
                    {item.osku}
                    <span className="dashboard-secondary-cell">{item.description}</span>
                  </td>
                  <td>
                    {item.baseline_volume.toLocaleString()} / {item.planned_volume.toLocaleString()} {item.uom}
                  </td>
                  <td>{formatMoney(item.regular_price, promotion.currency)}</td>
                  <td>
                    {item.spend_type} · {item.spend_treatment}
                    <span className="dashboard-secondary-cell">{item.spend_amount}</span>
                  </td>
                  <td>{formatMoney(item.landed_price, promotion.currency)}</td>
                  <td>{formatMoney(item.planned_spend, promotion.currency)}</td>
                  <td>{formatMoney(item.planned_contribution, promotion.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button component={RouterLink} sx={{ mt: 2 }} to="/promotions" variant="outlined">
          Back to Worklist
        </Button>
      </Paper>
    </Box>
  );
}

export function NewPromotionPage() {
  return (
    <Box className="dashboard-page">
      <PageHeader
        description="Start a new promotion plan."
        eyebrow="TPM LITE / PLANNING"
        title="New Promotion"
      />
      <Alert severity="info">
        Promotion creation is not implemented in the Phase 1 foundation yet. The existing
        promotion model, persistence, and create workflow must be established before a new plan
        can be saved.
      </Alert>
      <Button component={RouterLink} sx={{ mt: 2 }} to="/promotions" variant="outlined">
        Open Promotion Worklist
      </Button>
    </Box>
  );
}

export function IntegrationMonitorPage() {
  const query = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: getDashboardOverview,
  });
  const statuses = useMemo(() => {
    if (!query.data) return [];
    return [
      ["SAP S/4HANA Master Data", query.data.integration_status.sap_master_data],
      ["SAP Promotion Interface", query.data.integration_status.sap_promotions],
      ["P10 Arete", query.data.integration_status.p10_arete],
    ] as const;
  }, [query.data]);

  return (
    <Box className="dashboard-page">
      <PageHeader
        description="Business-level health summaries. Technical diagnostics are not exposed here."
        eyebrow="TPM LITE / OPERATIONS"
        title="Integration Monitor"
      />
      {query.isPending ? (
        <LoadingPanel />
      ) : query.isError ? (
        <ErrorPanel message={query.error.message} retry={() => void query.refetch()} />
      ) : (
        <>
          <Alert severity="info" sx={{ mb: 2 }}>
            {query.data.disclaimer}
          </Alert>
          <Paper className="dashboard-panel" elevation={0}>
            <ul className="dashboard-integrations">
              {statuses.map(([name, item]) => (
                <li key={name}>
                  <div>
                    <strong>{name}</strong>
                    <span>{item.summary}</span>
                  </div>
                  <Chip
                    color={item.status === "successful" ? "success" : "warning"}
                    label={item.status.replaceAll("_", " ")}
                    size="small"
                  />
                </li>
              ))}
            </ul>
          </Paper>
        </>
      )}
    </Box>
  );
}
