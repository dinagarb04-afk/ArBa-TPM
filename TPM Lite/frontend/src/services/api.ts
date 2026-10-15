import { z } from "zod";

export interface HealthResponse {
  status: "ok";
}

const promotionSchema = z.object({
  id: z.string(),
  promotion_id: z.string(),
  name: z.string(),
  plan_account: z.string(),
  start_date: z.string(),
  end_date: z.string(),
  planned_spend: z.number(),
  planned_contribution: z.number(),
  currency: z.string(),
  submitted_at: z.string(),
  status: z.enum(["pending_approval", "draft", "approved", "action_required"]),
  tactic: z.string(),
  market: z.string(),
  brand: z.string(),
  starting_soon: z.boolean(),
  negative_contribution: z.boolean(),
  validation_warnings: z.boolean(),
});

const attentionItemSchema = z.object({
  promotion_id: z.string(),
  name: z.string(),
  plan_account: z.string(),
  reason: z.string(),
  severity: z.enum(["warning", "critical"]),
  status: z.enum(["pending_approval", "draft", "approved", "action_required"]),
});

const integrationHealthSchema = z.object({
  status: z.enum(["successful", "attention_required", "unknown"]),
  summary: z.string(),
  last_event: z.string().nullable(),
});

export const dashboardOverviewSchema = z.object({
  data_source: z.literal("synthetic_development"),
  generated_at: z.string(),
  disclaimer: z.string(),
  kpis: z.object({
    pending_my_approval: z.number(),
    action_required: z.number(),
    upcoming_promotions: z.number(),
    planned_promo_spend: z.number(),
    currency: z.string(),
    upcoming_period_weeks: z.number(),
  }),
  pending_approvals: z.array(promotionSchema),
  attention_items: z.array(attentionItemSchema),
  upcoming_items: z.array(promotionSchema),
  planning_snapshot: z.object({
    baseline_volume: z.number(),
    promo_uplift: z.number(),
    total_forecast: z.number(),
    uom: z.string(),
    weekly_data: z.array(
      z.object({
        week: z.string(),
        baseline_volume: z.number(),
        promo_uplift: z.number(),
      }),
    ),
  }),
  promotion_financials: z.object({
    gross_sales_value: z.number(),
    planned_promo_spend: z.number(),
    net_sales_value: z.number(),
    planned_contribution: z.number(),
    negative_contribution_count: z.number(),
    currency: z.string(),
  }),
  integration_status: z.object({
    sap_master_data: integrationHealthSchema,
    sap_promotions: integrationHealthSchema,
    p10_arete: integrationHealthSchema,
  }),
  role_configuration: z.object({
    source: z.literal("not_configured"),
    available_roles: z.array(z.string()),
    preferred_widget_order: z.array(z.string()),
  }),
});

export type PromotionSummary = z.infer<typeof promotionSchema>;
export type AttentionItem = z.infer<typeof attentionItemSchema>;
export type DashboardOverview = z.infer<typeof dashboardOverviewSchema>;
export type DashboardFilter =
  | "all"
  | "pending-approval"
  | "action-required"
  | "upcoming"
  | "negative-contribution"
  | "planned-spend";

const promotionDetailSchema = promotionSchema.extend({
  description: z.string(),
  gross_sales_value: z.number(),
  net_sales_value: z.number(),
  validation_messages: z.array(z.string()),
  items: z.array(
    z.object({
      osku: z.string(),
      description: z.string(),
      uom: z.string(),
      baseline_volume: z.number(),
      planned_volume: z.number(),
      regular_price: z.number(),
      spend_type: z.string(),
      spend_amount: z.number(),
      spend_treatment: z.string(),
      landed_price: z.number(),
      planned_spend: z.number(),
      planned_contribution: z.number(),
      validation_messages: z.array(z.string()),
    }),
  ),
});

export type PromotionDetail = z.infer<typeof promotionDetailSchema>;

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";

async function getJson(path: string): Promise<unknown> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`The API returned HTTP ${response.status}.`);
  }

  return response.json() as Promise<unknown>;
}

export async function getLiveness(): Promise<HealthResponse> {
  const body = await getJson("/v1/health/live");

  if (
    typeof body !== "object" ||
    body === null ||
    !("status" in body) ||
    body.status !== "ok"
  ) {
    throw new Error("The API returned an unexpected health response.");
  }

  return { status: body.status };
}

export async function getDashboardOverview(): Promise<DashboardOverview> {
  const body = await getJson("/v1/dashboard/overview");
  return dashboardOverviewSchema.parse(body);
}

export async function getDashboardWorklist(
  filter: DashboardFilter,
): Promise<PromotionSummary[]> {
  const query = new URLSearchParams({ filter });
  const body: unknown = await getJson(`/v1/dashboard/worklist?${query}`);
  return z.array(promotionSchema).parse(body);
}

export async function getPromotionDetail(
  promotionId: string,
): Promise<PromotionDetail> {
  const body = await getJson(`/v1/promotions/${encodeURIComponent(promotionId)}`);
  return promotionDetailSchema.parse(body);
}
