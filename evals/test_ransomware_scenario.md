# Eval: ransomware_fast_recovery

## Goal

Check that increasing the cost-per-minute of outage increases total expected cost
and regret, while keeping the ranking of strategies stable.

## Steps

1. Run the ransomware_fast_recovery scenario with cost_per_minute_outage = 20000.
2. Run a variant where cost_per_minute_outage = 40000.
3. Confirm:
   - Total expected cost for all strategies increases (within rounding tolerance).
   - The strategy with the lowest cost in the baseline scenario is still the lowest
     cost in the higher-cost scenario.
