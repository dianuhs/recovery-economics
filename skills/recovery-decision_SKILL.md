---
name: recovery-decision
description: Compare downtime, risk, and regret cost across recovery strategies for a given scenario.
---

## When to use

Use this when a team is evaluating different recovery strategies
(for example: AI-assisted vs manual runbooks) and wants numbers instead of vibes.

## Inputs

- A scenario file in `scenarios/` (YAML)
- Each scenario defines:
  - business context (name, business_unit)
  - parameters (RTO, RPO, outage cost, risk levels)
  - strategies to compare

## Steps

1. Load the scenario file from `scenarios/` by name.
2. For each strategy:
   - Estimate expected downtime.
   - Estimate expected financial impact (outage cost + penalty risk + implementation cost).
3. Compute regret for each strategy as:
   - regret = cost(strategy) - min_cost(all_strategies)
4. Write results to:
   - `artifacts/reports/{scenario_name}_summary.md`
   - `artifacts/data/{scenario_name}_results.json`
5. In the summary, highlight:
   - The lowest-cost strategy.
   - Any strategies that are much worse but might be chosen for non-financial reasons
     (for example: simplicity, regulatory comfort).
