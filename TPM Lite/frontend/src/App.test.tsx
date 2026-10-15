import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardOverview, PromotionSummary } from "./services/api";
import {
  getDashboardOverview,
  getDashboardWorklist,
  getPromotionDetail,
} from "./services/api";
import App from "./App";

vi.mock("./services/api", () => ({
  getDashboardOverview: vi.fn(),
  getDashboardWorklist: vi.fn(),
  getPromotionDetail: vi.fn(),
}));

const pendingPromotion: PromotionSummary = {
  id: "promo-1045",
  promotion_id: "PROMO-1045",
  name: "Summer Price Drop",
  plan_account: "Tesco",
  start_date: "2026-05-04",
  end_date: "2026-05-17",
  planned_spend: 125000,
  planned_contribution: 48000,
  currency: "USD",
  submitted_at: "2026-05-02T10:00:00Z",
  status: "pending_approval",
  tactic: "Price Reduction",
  market: "UK",
  brand: "Home Care",
  starting_soon: true,
  negative_contribution: false,
  validation_warnings: true,
};

const overview: DashboardOverview = {
  data_source: "synthetic_development",
  generated_at: "2026-05-03T10:00:00Z",
  disclaimer: "Synthetic development data only.",
  kpis: {
    pending_my_approval: 6,
    action_required: 4,
    upcoming_promotions: 12,
    planned_promo_spend: 1240000,
    currency: "USD",
    upcoming_period_weeks: 4,
  },
  pending_approvals: [pendingPromotion],
  attention_items: [
    {
      promotion_id: pendingPromotion.id,
      name: pendingPromotion.name,
      plan_account: pendingPromotion.plan_account,
      reason: "Review unit cost basis.",
      severity: "warning",
      status: "action_required",
    },
  ],
  upcoming_items: [pendingPromotion],
  planning_snapshot: {
    baseline_volume: 420000,
    promo_uplift: 72000,
    total_forecast: 492000,
    uom: "CS",
    weekly_data: [
      { week: "W43", baseline_volume: 70000, promo_uplift: 12000 },
    ],
  },
  promotion_financials: {
    gross_sales_value: 5800000,
    planned_promo_spend: 1240000,
    net_sales_value: 4560000,
    planned_contribution: 1310000,
    negative_contribution_count: 2,
    currency: "USD",
  },
  integration_status: {
    sap_master_data: {
      status: "successful",
      summary: "Last synchronization successful",
      last_event: "2026-05-03T08:00:00Z",
    },
    sap_promotions: {
      status: "attention_required",
      summary: "2 promotions failed",
      last_event: "2026-05-03T09:00:00Z",
    },
    p10_arete: {
      status: "successful",
      summary: "Forecast transmission successful",
      last_event: "2026-05-03T08:30:00Z",
    },
  },
  role_configuration: {
    source: "not_configured",
    available_roles: [],
    preferred_widget_order: [],
  },
};

function renderApp(initialEntry = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(getDashboardOverview).mockResolvedValue(overview);
  vi.mocked(getDashboardWorklist).mockResolvedValue([pendingPromotion]);
  vi.mocked(getPromotionDetail).mockRejectedValue(new Error("Not requested in this test."));
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ArBa Trade Promotion Plan capability dashboard", () => {
  it("renders four actionable KPIs and the aggregated overview", async () => {
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Promotion Overview" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Pending My Approval: 6/ }),
    ).toHaveAttribute("href", "/promotions?filter=pending-approval");
    expect(
      screen.getByRole("link", { name: /Action Required: 4/ }),
    ).toHaveAttribute("href", "/promotions?filter=action-required");
    expect(
      screen.getByRole("link", { name: /Upcoming Promotions: 12/ }),
    ).toHaveAttribute("href", "/promotions?filter=upcoming");
    expect(
      screen.getByRole("link", { name: /Planned Promo Spend: USD 1\.24M/ }),
    ).toHaveAttribute("href", "/promotions?filter=planned-spend");
    expect(screen.getByText("420K CS")).toBeInTheDocument();
    expect(screen.getByText("492K CS")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Weekly baseline volume/ })).toBeInTheDocument();
    expect(screen.getByText("DEMO DATA — Synthetic development data only.")).toBeInTheDocument();
  });

  it("keeps the new-promotion entry point and routes approvals to review without dashboard decisions", async () => {
    renderApp();

    expect(
      await screen.findByRole("link", { name: "+ New Promotion" }),
    ).toHaveAttribute("href", "/promotions/new");
    expect(
      screen.getByRole("link", { name: "Review PROMO-1045 Summer Price Drop" }),
    ).toHaveAttribute("href", "/promotions/promo-1045");
    expect(screen.queryByRole("button", { name: /approve|reject/i })).not.toBeInTheDocument();
    expect(screen.getByText("Needs your attention")).toBeInTheDocument();
    expect(screen.getByText("Integration Status")).toBeInTheDocument();
  });

  it("opens the filtered Promotion Worklist when an approval KPI is activated", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(
      await screen.findByRole("link", { name: /Pending My Approval: 6/ }),
    );

    expect(
      await screen.findByRole("heading", { name: "Promotion Worklist" }),
    ).toBeInTheDocument();
    expect(getDashboardWorklist).toHaveBeenCalledWith("pending-approval");
    expect(screen.getByText("Summer Price Drop")).toBeInTheDocument();
  });

  it("shows an explicit empty state when there are no pending approvals", async () => {
    vi.mocked(getDashboardOverview).mockResolvedValue({
      ...overview,
      pending_approvals: [],
    });
    renderApp();

    expect(
      await screen.findByText("No promotions are waiting for your approval."),
    ).toBeInTheDocument();
    expect(screen.getByText("You're all caught up.")).toBeInTheDocument();
  });

  it("supports retry after an overview API error", async () => {
    vi.mocked(getDashboardOverview)
      .mockRejectedValueOnce(new Error("API unavailable"))
      .mockResolvedValueOnce(overview);
    renderApp();

    expect(
      await screen.findByText(/The promotion overview could not be loaded/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", { name: "Promotion Overview" }),
    ).toBeInTheDocument();
  });
});
