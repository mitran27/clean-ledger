"""memory.py - past-case memory: embeddings to shortlist, reranker to order.

  search("fan-in from new accounts then wire to the Caymans")
    -> embeds the query, takes the 6 nearest closed cases by cosine, reranks them,
       returns the best 3 with both scores.

Embedding and rerank models are tier "unverified", so only pseudonymous pattern text may
be sent. assert_pseudonymous() refuses any text that contains a customer name.

Closed cases = samples/past_cases.json (synthetic seed) + memory/learned.jsonl (cases this
system closed; added by remember()).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import call_model  # noqa: E402
import ledger  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "samples" / "past_cases.json"
LEARNED = ROOT / "memory" / "learned.jsonl"
CACHE = ROOT / ".cache" / "embeddings.json"
EMBED = "Qwen/Qwen3-Embedding-0.6B"
RERANK = "Qwen/Qwen3-Reranker-0.6B"


def load_cases() -> list[dict]:
    cases = json.loads(SEED.read_text())
    if LEARNED.exists():
        cases += [json.loads(l) for l in LEARNED.read_text().splitlines() if l]
    return cases


def assert_pseudonymous(text: str) -> None:
    low = text.lower()
    for a in ledger.accounts().values():
        if a["name"].lower() in low:
            raise call_model.PolicyError(f"text contains the customer name '{a['name']}'; "
                                         f"{EMBED}/{RERANK} are not confirmed TEE models, so names may not be sent")


def _embed(texts: list[str]) -> list[list[float]]:
    call_model.check_policy(EMBED, raw=False)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    keys = [hashlib.sha256(f"{EMBED}|{t}".encode()).hexdigest() for t in texts]
    missing = [(k, t) for k, t in zip(keys, texts) if k not in cache]
    if missing:
        r = call_model.request("POST", "/embeddings", {"model": EMBED, "input": [t for _, t in missing]})
        for (k, _), d in zip(missing, sorted(r["data"], key=lambda d: d["index"])):
            cache[k] = d["embedding"]
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return [cache[k] for k in keys]


def _cos(a: list[float], b: list[float]) -> float:
    d = sum(x * y for x, y in zip(a, b))
    return d / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def search(text: str, k: int = 3, pool: int = 6, exclude_case: str | None = None) -> list[dict]:
    import guard  # local import: guard -> call_model, no cycle
    guard.assert_no_personal_data(text)  # customer names + NEAR privacy filter, before non-TEE models
    cases = [c for c in load_cases() if exclude_case is None or c.get("source_case") != exclude_case]
    if not cases:
        return []
    vecs = _embed([c["summary"] for c in cases])
    q = _embed([text])[0]
    ranked = sorted(((_cos(q, v), c) for v, c in zip(vecs, cases)), key=lambda x: -x[0])[:pool]
    call_model.check_policy(RERANK, raw=False)
    rr = call_model.request("POST", "/rerank", {"model": RERANK, "query": text,
                                                "documents": [c["summary"] for _, c in ranked]})
    out = []
    for res in sorted(rr["results"], key=lambda x: -float(x["relevance_score"]))[:k]:
        sim, c = ranked[res["index"]]
        out.append({"case_id": c["case_id"], "title": c["title"], "outcome": c["outcome"],
                    "similarity": round(sim, 3), "rerank_score": round(float(res["relevance_score"]), 3),
                    "summary": c["summary"]})
    return out


def remember(case: str, summary: str, outcome: str) -> dict | None:
    """Add a closed case to memory (pseudonymous summary only). One entry per source case."""
    cases = load_cases()
    if any(c.get("source_case") == case for c in cases):
        return None
    assert_pseudonymous(summary)
    n = max(int(c["case_id"].split("-")[1]) for c in cases) + 1
    entry = {"case_id": f"CASE-{n:03d}", "closed": "2026-11-11", "outcome": outcome,
             "title": "Learned from " + case, "summary": summary, "source_case": case}
    LEARNED.parent.mkdir(exist_ok=True)
    with LEARNED.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


OUTCOME = {"file_sar": "SAR filed", "freeze_account": "account frozen",
           "request_info": "information requested", "close_case": "closed"}


def remember_case(case: str, actions: list[str]) -> dict | None:
    """Store a pseudonymous pattern summary of a case that just executed (no names, no ids)."""
    f = ledger.features().get(case.removeprefix("case-"))
    if not f:
        return None
    text = (f"Account {f['account_age_days']} days old received about ${f['in_usd']:,.0f} from "
            f"{f['distinct_senders']} accounts, {f['new_account_senders']} of them opened within the last 60 days. "
            f"It sent {f['pass_through_ratio']:.0%} of the money onward"
            f"{', including an offshore wire.' if f['high_risk_wires_out'] else '.'}")
    return remember(case, text, "; ".join(dict.fromkeys(OUTCOME[a] for a in actions if a in OUTCOME)) or "closed")


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "six new accounts send just-under-10k transfers to one account which wires everything to the Cayman Islands"
    try:
        hits = search(q)
    except call_model.PolicyError as e:
        sys.exit(f"POLICY REFUSED: {e}")
    for m in hits:
        print(f"{m['case_id']} sim={m['similarity']:.2f} rerank={m['rerank_score']:.2f} | {m['title']} -> {m['outcome']}")
