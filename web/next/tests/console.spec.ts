import { test, expect, type Page } from "@playwright/test";
import type { Negotiation } from "../lib/negotiation";

const fixture = (): Negotiation => ({
  thread_id: "actual-live-thread", subject: "Actual live negotiation",
  our_email: "buyer@example.com", counterparty_email: "supplier@example.com",
  commodity: "Primary aluminium", quantity: 100, price_unit: "metric tonne", currency: "USD",
  buyer_region: "Europe", supplier_region: "North America",
  status: "awaiting", mandate: { floor_price_eur: 3250, target_price_eur: 3000, max_lead_time_days: 30 },
  our_position: { unit_price_eur: 3000, lead_time_days: 21, note: "" },
  their_position: { unit_price_eur: 3300, lead_time_days: 21, note: "" },
  market_context: "Market evidence from the backend", max_turns: 6,
  pending_draft: "We can offer 3200.00 USD per metric tonne at 21 days lead time.",
  turns: [{ index: 0, direction: "in", subject: "Actual live negotiation", body: "We can supply: 3300.00 USD per metric tonne at 21 days lead time.", at: 1700000000, tier: "escalate", model_used: "actual-provider-model", approved_by_human: false, reason: "Review the supplier terms" }],
});

async function api(page: Page, initial: Negotiation | null = fixture()) {
  const store = { state: initial, failReads: false, writes: [] as { path: string; body: Record<string, unknown> | null }[] };
  await page.route("http://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS", "Access-Control-Allow-Headers": "Content-Type" } });
    if (path === "/health") return route.fulfill({ json: { ok: true, mode: "demo_pair", engine: "OpenRouter drafting + bounded demo policy", integrations: { openrouter_configured: true, exa_configured: true }, accounts: { buyer: { email: "buyer@example.com", ok: true, detail: "Connected" }, supplier: { email: "supplier@example.com", ok: true, detail: "Connected" } }, setup: { accounts: [{ id: "primary", email: "buyer@example.com" }, { id: "secondary", email: "supplier@example.com" }], commodities: [{ id: "aluminium", label: "Primary aluminium", quantity: 100, price_unit: "metric tonne" }, { id: "copper", label: "Copper cathode", quantity: 50, price_unit: "metric tonne" }], regions: ["Europe", "North America", "East Asia"], defaults: { buyer_account: "primary", supplier_account: "secondary", commodity: "aluminium", buyer_region: "Europe", supplier_region: "North America" } } } });
    if (request.method() === "GET") {
      if (store.failReads) return route.fulfill({ status: 503, json: { detail: "Backend temporarily unavailable" } });
      return route.fulfill({ status: store.state ? 200 : 404, json: store.state ?? { detail: "No negotiation yet" } });
    }
    const body = request.postDataJSON();
    store.writes.push({ path, body });
    if (path === "/negotiation") store.state = { ...fixture(), thread_id: "new-live-thread", status: "idle", pending_draft: "" };
    if (path.endsWith("/mandate") && store.state) store.state.mandate.floor_price_eur = body.floor_price_eur;
    if (path.endsWith("/reject") && store.state) { store.state.status = "closed"; store.state.our_position.note = "Demo stopped by you."; }
    if (path.endsWith("/approve") && store.state) { store.state.status = "idle"; store.state.pending_draft = ""; }
    return route.fulfill({ json: store.state });
  });
  await page.goto("/");
  return store;
}

test("approval sends the edited text and the displayed thread ID", async ({ page }) => {
  const store = await api(page);
  await expect(page.getByRole("heading", { name: "Actual live negotiation", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Edit draft reply" }).fill("Approved edited terms: 3200.00 USD at 21 days.");
  await page.getByRole("button", { name: "Approve & send" }).click();
  await expect.poll(() => store.writes).toEqual([{ path: "/negotiation/approve", body: { thread_id: "actual-live-thread", edited_body: "Approved edited terms: 3200.00 USD at 21 days." } }]);
  await expect(page.getByText("actual-provider-model", { exact: true })).toBeVisible();
  await expect(page.getByText("Allow this exception once")).toHaveCount(0);
});

test("blank approval is disabled and limit changes target the live thread", async ({ page }) => {
  const store = await api(page);
  await page.getByRole("textbox", { name: "Edit draft reply" }).fill("");
  await expect(page.getByRole("button", { name: "Approve & send" })).toBeDisabled();
  await page.getByRole("slider").fill("3200");
  await expect.poll(() => store.writes).toEqual([{ path: "/negotiation/mandate", body: { thread_id: "actual-live-thread", floor_price_eur: 3200 } }]);
});

test("active agents can stop and a closed run can restart", async ({ page }) => {
  const store = await api(page, { ...fixture(), status: "idle", pending_draft: "" });
  await expect(page.getByRole("button", { name: "Set up negotiation" })).toBeDisabled();
  await page.getByRole("button", { name: "Stop both agents" }).click();
  await expect(page.getByText("Demo stopped by you.")).toBeVisible();
  await expect(page.getByText("Deal agreed", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Configure another negotiation" }).click();
  await expect(page.getByRole("heading", { name: "Choose who buys and who sells" })).toBeVisible();
  await page.getByRole("button", { name: "Research market & start agents" }).click();
  await expect(page.getByText("new-live-thread", { exact: true })).toBeVisible();
  expect(store.writes[0]).toEqual({ path: "/negotiation/reject", body: { thread_id: "actual-live-thread" } });
  expect(store.writes[1].path).toBe("/negotiation");
});

test("a connection failure retains the real conversation", async ({ page }) => {
  const store = await api(page);
  await expect(page.getByRole("heading", { name: "Actual live negotiation", exact: true })).toBeVisible();
  store.failReads = true;
  await expect(page.getByRole("alert").filter({ hasText: "Backend temporarily unavailable" })).toBeVisible({ timeout: 6000 });
  await expect(page.getByText("actual-live-thread", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve & send" })).toBeDisabled();
  expect(store.writes).toEqual([]);
});

test("an empty server starts a new thread and stays usable on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const store = await api(page, null);
  await expect(page.getByRole("heading", { name: "Choose who buys and who sells" })).toBeVisible();
  await page.getByRole("button", { name: "Research market & start agents" }).click();
  await expect(page.getByText("new-live-thread", { exact: true })).toBeVisible();
  expect(store.writes[0].path).toBe("/negotiation");
  expect(store.writes[0].body).toEqual({ buyer_account: "primary", supplier_account: "secondary", commodity: "aluminium", buyer_region: "Europe", supplier_region: "North America" });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});

test("a backend restart clears the obsolete thread and allows a fresh run", async ({ page }) => {
  const store = await api(page, { ...fixture(), status: "idle", pending_draft: "" });
  await expect(page.getByText("actual-live-thread", { exact: true })).toBeVisible();
  store.state = null;
  await expect(page.getByText("actual-live-thread", { exact: true })).toHaveCount(0, { timeout: 6000 });
  await expect(page.getByRole("button", { name: "Research market & start agents" })).toBeEnabled();
  await page.getByRole("button", { name: "Research market & start agents" }).click();
  await expect(page.getByText("new-live-thread", { exact: true })).toBeVisible();
});

test("the selected inbox roles, regions, and commodity are sent to the backend", async ({ page }) => {
  const store = await api(page, null);
  await page.getByRole("combobox", { name: "Buyer inbox" }).selectOption("secondary");
  await page.getByRole("combobox", { name: "Seller inbox" }).selectOption("primary");
  await page.getByRole("combobox", { name: "Buyer region" }).selectOption("East Asia");
  await page.getByRole("combobox", { name: "Seller region" }).selectOption("Europe");
  await page.getByRole("combobox", { name: "Commodity" }).selectOption("copper");
  await page.getByRole("button", { name: "Research market & start agents" }).click();
  await expect.poll(() => store.writes[0]).toEqual({
    path: "/negotiation",
    body: { buyer_account: "secondary", supplier_account: "primary", commodity: "copper", buyer_region: "East Asia", supplier_region: "Europe" },
  });
});

test("the same inbox cannot be both buyer and seller", async ({ page }) => {
  const store = await api(page, null);
  await page.getByRole("combobox", { name: "Buyer inbox" }).selectOption("secondary");
  await expect(page.getByText("Buyer and seller must use different inboxes.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Research market & start agents" })).toBeDisabled();
  expect(store.writes).toEqual([]);
});
