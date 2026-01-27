#!/usr/bin/env bash
# Example: compare ransomware strategies for the sample scenario.

set -euo pipefail

recovery-economics   --scenario-file scenarios/ransomware_fast_recovery.yml   --compare-strategies
