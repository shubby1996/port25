"use client";

import { CopilotChat, useComponent } from "@copilotkit/react-core/v2";
import { z } from "zod";

const progressionSchema = z.object({
  phase: z.enum(["received", "routing", "drafting", "escalated", "sent"]),
  headline: z.string(), detail: z.string(),
  tier: z.enum(["routine", "complex", "escalate"]), model: z.string().optional()
});
type Progression = z.infer<typeof progressionSchema>;

function NegotiationProgression({ phase, headline, detail, tier, model }: Progression) {
  const steps = ["received", "routing", "drafting", "sent"];
  const current = phase === "escalated" ? 3 : steps.indexOf(phase);
  return <section className={`agent-progression ${tier}`}>
    <div className="progression-meta"><span className={`tier ${tier}`}>{tier}</span>{model && <span>{model}</span>}</div>
    <div className="progression-rail">{steps.map((step, index) => <span key={step} className={index <= current ? "done" : ""}>{step}</span>)}</div>
    <strong>{headline}</strong><p>{detail}</p>
  </section>;
}

/** Registers an application component as a CopilotKit generative-UI tool. */
export function CopilotProgress() {
  useComponent({
    name: "render_negotiation_progression",
    description: "Render a concise Port 25 negotiation-progress card whenever explaining an inbound email, routing decision, drafted reply, send, or escalation. Use a plain-language headline and detail.",
    parameters: progressionSchema, render: NegotiationProgression
  });
  return <CopilotChat className="copilot-chat" labels={{ welcomeMessageText: "Ask what changed in the negotiation, why the agent paused, or how the mandate affects the next reply.", chatInputPlaceholder: "Ask about this negotiation…" }} />;
}
