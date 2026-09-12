export type Status = "idle" | "thinking" | "awaiting" | "closed";
export type Tier = "routine" | "complex" | "escalate";
export type Turn = { index: number; direction: "in" | "out"; subject: string; body: string; at: number; tier?: Tier | null; reason: string; model_used: string; approved_by_human: boolean };
export type Negotiation = {
  thread_id: string; subject: string; our_email: string; counterparty_email: string; status: Status;
  mandate: { floor_price_eur: number; target_price_eur: number; max_lead_time_days: number };
  our_position: { unit_price_eur: number | null; lead_time_days: number | null };
  their_position: { unit_price_eur: number | null; lead_time_days: number | null };
  turns: Turn[]; pending_draft: string;
};

// FastAPI serves on 8000 in local development. Override this for a deployed API.
const api = process.env.NEXT_PUBLIC_PORT25_API ?? "http://localhost:8000";
async function request(path: string, options?: RequestInit): Promise<Negotiation> {
  const response = await fetch(`${api}${path}`, { ...options, headers: { "Content-Type": "application/json", ...options?.headers } });
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}
export const getNegotiation = () => request("/negotiation", { cache: "no-store" });
export const startNegotiation = () => request("/negotiation", { method: "POST" });
export const setFloor = (floor_price_eur: number) => request("/negotiation/mandate", { method: "PATCH", body: JSON.stringify({ floor_price_eur }) });
export const approve = (edited_body: string) => request("/negotiation/approve", { method: "POST", body: JSON.stringify({ edited_body }) });
export const reject = () => request("/negotiation/reject", { method: "POST" });
