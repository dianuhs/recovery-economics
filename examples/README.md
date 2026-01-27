# Recovery Economics examples

A few quick examples of how to run the CLI once the package is installed
(or from the repo root with `python -m recovery_economics.cli`).

## 1. Compare ransomware strategies (scenario file)

```bash
recovery-economics \  --scenario-file scenarios/ransomware_fast_recovery.yml \  --compare-strategies
```

## 2. Single strategy, JSON output

```bash
recovery-economics \  --scenario-file scenarios/ransomware_fast_recovery.yml \  --strategy ai_assisted \  --json
```

## 3. AI decision narrative (requires OPENAI_API_KEY)

```bash
export OPENAI_API_KEY=your_key_here

recovery-economics \  --scenario-file scenarios/ransomware_fast_recovery.yml \  --strategy hybrid \  --ai-narrative
```
