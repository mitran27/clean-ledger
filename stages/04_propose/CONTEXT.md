# 04_propose - agent proposes, policy gate decides

One job: turn findings into proposed actions and run each through the policy gate.

## Inputs
- Working (this run): `../03_investigate/output/<case>.findings.md`
- Reference (every run): `../../_shared/action-policy.json`

Do NOT load: raw CSVs, the trace (the findings are the contract).

## Process
1. If `03_investigate/output/check.md` does not start with `pass`, stop.
2. Run `python _tools/policy_gate.py <case>`: reads the agent's proposed actions from the findings, checks each against `action-policy.json` (risk, evidence count, cited txn ids, amount caps, action count).
3. Each proposal gets `allowed` or `denied: <rule>`. There is no human step: the gate is the decision.

## Outputs
- `<case>.proposals.json` -> `output/`

## Check
Script: `check.md` = `pass` if every proposal has a verdict and no unknown action was allowed.
