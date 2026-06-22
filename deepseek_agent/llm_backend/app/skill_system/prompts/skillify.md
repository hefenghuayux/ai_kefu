# Skillify MVP

You convert one completed customer-service conversation into a reusable ai_kefu Skill.

The Skill must capture repeatable workflow, decision process, constraints, tools to consult, and success criteria. It must not store mutable business facts as instructions.

## Inputs

User description:
<user_description>
{description}
</user_description>

Session summary:
<session_summary>
{session_summary}
</session_summary>

Transcript events:
<transcript_events>
{transcript_events}
</transcript_events>

Existing skill manifest:
<existing_skill_manifest>
{existing_skill_manifest}
</existing_skill_manifest>

## Rules

- Output strict JSON only. Do not wrap it in markdown fences.
- Do not include comments in the JSON.
- Extract a repeatable workflow, not one-time facts.
- Do not write concrete order IDs, phone numbers, addresses, payment status, inventory counts, prices, logistics state, or after-sales progress into the Skill.
- If the workflow depends on order, inventory, price, logistics, or after-sales status, represent that as a constraint requiring realtime tools.
- allowed_tools must only use these names: knowledge_query, order_query, inventory_query, logistics_query, after_sales_query, customer_profile_read, memory_read, transcript_read.
- context must be inline or fork. Prefer inline unless the workflow is self-contained and does not require mid-process user confirmation.
- The name must be lowercase kebab-case, using only letters, digits, and hyphens.
- Every step must include success_criteria.

## JSON Schema

{
  "name": "skill-name",
  "description": "one-line description",
  "when_to_use": "Use when...",
  "allowed_tools": ["knowledge_query"],
  "argument_hint": "<optional>",
  "arguments": ["customer_issue"],
  "context": "inline",
  "title": "Skill Title",
  "inputs": ["`customer_issue`: ..."],
  "goal": "Clear goal for the workflow.",
  "steps": [
    {
      "title": "Step name",
      "action": "What to do.",
      "success_criteria": "What proves this step is done.",
      "artifacts": ["optional artifact"],
      "rules": ["optional rule"],
      "human_checkpoint": null
    }
  ],
  "constraints": ["Do not store realtime facts; query tools when needed."],
  "source_notes": ["Generated from conversation ..."]
}
