# Policy Lab chatbot roadmap

The chatbot is a later optional interface, not part of the static-site deployment or the daily policy-news bot.

## Intended use

- Explain Policy Lab methods, cases and source-linked global policy briefs.
- Help a researcher turn a policy question into a draft case proposal.
- Retrieve reviewed repository content and point to the original record.
- Never present model output as an official policy decision or participant opinion.

## Low-cost architecture

```text
static site chat UI
  → rate-limited serverless API
    → reviewed content retrieval
      → provider adapter (Solar Open2 / Claude / later approved model)
```

- Do not run a dedicated VM while traffic is low.
- Do not expose provider API keys or unrestricted API endpoints in browser code.
- Use a separate serverless service from the public static site and the event participant service.
- Start with reviewed site/repository documents only; do not index participant responses or private event data.
- Apply per-IP/session quotas, maximum prompt/context/output sizes, concurrency limits and a monthly budget alert.
- Log cost and failure metadata without retaining the user's full question by default.
- Provide a visible source list, uncertainty notice and feedback/report path with every answer.

## Activation gates

1. Provider, hosting account, billing budget and hard shutdown threshold selected.
2. Threat model and abuse/rate-limit design reviewed.
3. Retrieval corpus contains only approved public material.
4. Privacy notice and retention period approved.
5. Cost test completed with realistic traffic.
6. Human owner accepts launch and shutdown thresholds.
