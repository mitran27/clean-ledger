"""build_ui.py - render app/ui/index.html from the real stage outputs.

Reads every stage's CONTEXT.md, output files and check.md, plus the agent's
trace, and injects them as JSON into app/ui/template.html. Re-run after any
pipeline run; the page always shows what is on disk.

Usage: python _tools/build_ui.py [case]   (default case-ACC-M1)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "stages"
UI = ROOT / "app" / "ui"


def section(md: str, name: str) -> list[str]:
    m = re.search(rf"^## {name}\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    if not m:
        return []
    return [l.lstrip("-0123456789. ").strip() for l in m.group(1).strip().splitlines() if l.strip()]


def stage_info(folder: Path) -> dict:
    ctx = (folder / "CONTEXT.md").read_text()
    title = ctx.splitlines()[0].lstrip("# ")
    out = folder / "output"
    files = sorted(p.name for p in out.iterdir() if p.is_file() and p.name not in (".gitkeep", "check.md"))
    check = (out / "check.md").read_text().strip() if (out / "check.md").exists() else "not run"
    return {"folder": folder.name, "title": title,
            "job": ctx.split("One job: ", 1)[1].split("\n", 1)[0] if "One job: " in ctx else "",
            "inputs": section(ctx, "Inputs"), "outputs": section(ctx, "Outputs"),
            "check_rule": " ".join(section(ctx, "Check")), "files": files, "check": check}


def main() -> None:
    case = sys.argv[1] if len(sys.argv) > 1 else "case-ACC-M1"
    acct = case.removeprefix("case-")
    inv = ST / "03_investigate" / "output"
    trace = [json.loads(l) for l in (inv / f"{case}.trace.jsonl").read_text().splitlines() if l]
    for t in trace:  # keep the page light: summarize big results
        r = t["result"]
        t["result_preview"] = (r[:4] if isinstance(r, list) else
                               {"accounts": r["accounts"], "edges": r["edges"][:5]} if isinstance(r, dict) and "edges" in r
                               else r)
        t["result_count"] = len(r) if isinstance(r, list) else len(r.get("edges", [])) if isinstance(r, dict) else 0
        del t["result"]
    accounts = ledger.accounts()
    prompt_system = ("You are an anti-money-laundering investigator. Use tools to gather evidence about the "
                     "subject account, deciding each next step from what you found. Cite transaction ids for "
                     "every claim.\n\nRUBRIC:\n" + (ROOT / "_shared" / "risk-rubric.md").read_text())
    data = {
        "case": case, "account": acct,
        "subject": {**accounts.get(acct, {}), "features": ledger.features().get(acct, {})},
        "stages": [stage_info(p) for p in sorted(ST.iterdir()) if p.is_dir()],
        "shared": sorted(p.name for p in (ROOT / "_shared").iterdir()),
        "alerts": json.loads((ST / "02_screen" / "output" / "alerts.json").read_text())[:5],
        "trace": trace,
        "findings": (inv / f"{case}.findings.md").read_text(),
        "simulated": json.loads((inv / f"{case}.actions.json").read_text()).get("simulated", False),
        "actions": json.loads((inv / f"{case}.actions.json").read_text()),
        "outbox": [json.loads(l) for l in (ST / "04_execute" / "output" / "outbox.jsonl").read_text().splitlines() if l],
        "policy_models": json.loads((ROOT / "_shared" / "policy.json").read_text())["models"],
        "prompt": {"system": prompt_system, "user": f"Investigate {acct}. Case id {case}.",
                   "subject_name": accounts.get(acct, {}).get("name", "")},
        "ingest": json.loads((ST / "01_ingest" / "output" / "ingest.json").read_text()),
    }
    html = (UI / "template.html").read_text().replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    (UI / "index.html").write_text(html)
    print(f"wrote app/ui/index.html ({len(html) // 1024} KB) for {case}")


if __name__ == "__main__":
    main()
