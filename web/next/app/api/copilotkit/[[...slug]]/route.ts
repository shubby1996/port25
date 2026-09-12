import { BuiltInAgent, CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";

// The Python backend remains the authority for email, mandates, and escalation.
// CopilotKit powers the supervision layer and its generative UI components.
const runtime = new CopilotRuntime({
  agents: { default: new BuiltInAgent({
    model: "openai/gpt-4.1-mini",
    prompt: "You supervise Port 25, an autonomous supply-contract negotiation by email. Explain progress in concise plain language. Whenever discussing a negotiation event, call render_negotiation_progression first; do not make up prices or claim an email was sent unless the user tells you so."
  }) }
});

const handler = createCopilotRuntimeHandler({ runtime, basePath: "/api/copilotkit" });
export const GET = handler;
export const POST = handler;
