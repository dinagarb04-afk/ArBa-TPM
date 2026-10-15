export type User = {
  id: number;
  email: string;
  name: string;
  role: "PLANNER" | "APPROVER" | "ADMIN" | "VIEWER";
  admin_sales_org_access?: string[];
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Retain the HTTP error message when the response isn't JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}
