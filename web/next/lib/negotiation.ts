export type Status = "idle" | "thinking" | "awaiting" | "closed";
export type Tier = "routine" | "complex" | "escalate";
export type Position = { unit_price_eur: number | null; lead_time_days: number | null; note: string };
export type Turn = { index: number; direction: "in" | "out"; subject: string; body: string; at: number; tier?: Tier | null; reason: string; model_used: string; approved_by_human: boolean };
export type Negotiation = {
  thread_id: string; subject: string; our_email: string; counterparty_email: string; status: Status;
  mandate: { floor_price_eur: number; target_price_eur: number; max_lead_time_days: number };
  our_position: Position; their_position: Position; turns: Turn[]; pending_draft: string;
  market_context: string; max_turns: number;
};
export type Health = {
  ok: boolean; transport: string; mode?: string; engine?: string; detail?: string;
  accounts?: Record<string, { email: string; ok: boolean; detail: string }>;
  integrations?: { openrouter_configured: boolean; exa_configured: boolean };
};
const base = process.env.NEXT_PUBLIC_PORT25_API ?? "http://127.0.0.1:8000";
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(base + path, { ...options, headers: { "Content-Type": "application/json", ...options?.headers } });
  const data = await response.json();
  if (!response.ok) throw new ApiError(response.status, typeof data.detail === "string" ? data.detail : "The request could not be completed.");
  return data;
}
export const getNegotiation = () => request<Negotiation>("/negotiation", { cache: "no-store" });
export const getHealth = () => request<Health>("/health", { cache: "no-store" });
export const startNegotiation = () => request<Negotiation>("/negotiation", { method: "POST" });
export const setMandate = (thread_id: string, patch: Partial<Negotiation["mandate"]>) => request<Negotiation>("/negotiation/mandate", { method: "PATCH", body: JSON.stringify({ thread_id, ...patch }) });
export const approve = (thread_id: string, edited_body: string) => request<Negotiation>("/negotiation/approve", { method: "POST", body: JSON.stringify({ thread_id, edited_body }) });
export const reject = (thread_id: string) => request<Negotiation>("/negotiation/reject", { method: "POST", body: JSON.stringify({ thread_id }) });
