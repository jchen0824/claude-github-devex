#!/usr/bin/env python3
"""Grade iteration-2 runs by inspecting fixture post-state and response text."""
import json, re
from pathlib import Path

W = Path(__file__).resolve().parent
OLD_ACCT, OLD_ORG = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
NEW_ACCT, NEW_ORG = "cccccccc-3333-4333-8333-cccccccccccc", "dddddddd-4444-4444-8444-dddddddddddd"
ACC_B = "eeeeeeee-5555-4555-8555-eeeeeeeeeeee"
OLD_EMAIL, OTHER_EMAIL = "previous.owner@example.com", "other.person@example.com"
COLLIDE = "local_code0003-0000-4000-8000-000000000003.json"
CODE, AGENT = "claude-code-sessions", "local-agent-mode-sessions"
LIVE = "Library/Application Support/Claude"


def bucket(root, store, acct, org): return root / store / acct / org


def landed(root: Path, store: str, prefix: str) -> list[str]:
    """Records matching `prefix` in any bucket that is not a source bucket.

    A run may legitimately target a bucket keyed by the live account's UUIDs
    rather than the one the fixture ships, so the destination is not fixed.
    """
    out, store_dir = [], root / store
    if not store_dir.is_dir():
        return out
    for acct in store_dir.iterdir():
        if not acct.is_dir() or acct.name in (OLD_ACCT, ACC_B, "skills-plugin"):
            continue
        for org in acct.iterdir():
            if org.is_dir():
                out += [n for n in names(org) if n.startswith(prefix)]
    return out
def names(d): return sorted(p.name for p in d.glob("local_*.json")) if d.is_dir() else []
def jload(p):
    try: return json.loads(p.read_text())
    except Exception: return {}
def A(text, passed, evidence): return {"text": text, "passed": bool(passed), "evidence": evidence}
def has(t, *words): return any(w in t for w in words)


def grade(fixture: Path, resp: str, kind: str):
    r = resp.lower()
    code_src = bucket(fixture, CODE, OLD_ACCT, OLD_ORG)
    code_dst = bucket(fixture, CODE, NEW_ACCT, NEW_ORG)
    ag_src   = bucket(fixture, AGENT, OLD_ACCT, OLD_ORG)
    ag_dst   = bucket(fixture, AGENT, NEW_ACCT, NEW_ORG)
    other_src = bucket(fixture, CODE, ACC_B, OLD_ORG)

    migrated_code = landed(fixture, CODE, "local_code")
    leaked_other  = [n for n in names(code_dst) if n.startswith("local_other")]

    if kind == "ambiguous-three-account-source":
        skills_leak = list(code_dst.glob("**/cache.json")) + list(ag_dst.glob("**/cache.json"))
        return [
            A("All 12 of the intended source account's Claude Code records reached the target",
              len(migrated_code) == 12, f"{len(migrated_code)} of 12 migrated"),
            A("Not one record belonging to the other person was copied into the target",
              not leaked_other, f"{len(leaked_other)} of the colleague's records leaked into the target"),
            A("The other person's own bucket was left completely untouched",
              len(names(other_src)) == 5, f"{len(names(other_src))} of 5 still in their bucket"),
            # Only the filesystem outcome matters here. Naming skills-plugin in the
            # write-up to say it was left alone is correct behaviour, not a failure.
            A("The skills-plugin directory was not treated as an account (nothing from it reached the target)",
              not skills_leak, f"{len(skills_leak)} skills-plugin artifacts in target"),
            A("The response identifies the accounts by the email embedded in their records, naming both candidates",
              OLD_EMAIL in resp and OTHER_EMAIL in resp,
              f"source email named: {OLD_EMAIL in resp}; colleague email named: {OTHER_EMAIL in resp}"),
            A("The response flags that two accounts share the same organization UUID, so the directory path alone cannot separate them",
              has(r, "same org", "shared org", "same organization", "share the same", "identical org")
              or (r.count("bbbbbbbb") >= 2),
              "shared-org ambiguity called out" if has(r, "same org", "shared org", "same organization", "share the same") else "no explicit shared-org note"),
            A("The target's pre-existing records survived",
              any(n.startswith("local_existing") for n in names(code_dst)),
              f"target holds {len(names(code_dst))} records"),
        ]

    if kind == "collision-must-not-clobber":
        col = code_dst / COLLIDE
        title = jload(col).get("title", "")
        non_collide = [n for n in migrated_code if n != COLLIDE]
        return [
            A("The target's colliding record kept its own content and was not overwritten by the source's version",
              title == "TARGET VERSION - MUST SURVIVE", f"title is {title!r}"),
            A("The other 11 source records migrated normally",
              len(non_collide) == 11, f"{len(non_collide)} of 11 migrated"),
            A("The response tells the user a collision was found and skipped",
              has(r, "collision", "collid", "skipped", "already exist", "conflict"),
              "collision reported" if has(r, "collision", "collid", "skipped", "already exist", "conflict") else "no mention of the collision"),
            A("The target's other pre-existing record survived",
              any(n.startswith("local_existing") for n in names(code_dst)),
              f"target holds {len(names(code_dst))} records"),
            A("The source bucket was not emptied (nothing lost if the user wants to redo it)",
              len(names(code_src)) == 12, f"{len(names(code_src))} of 12 still in source"),
        ]

    if kind == "live-tree-mismatch":
        return [
            A("The response states that the given folder is not the tree the running app reads",
              has(r, "not the live", "not the directory", "isn't the live", "not what the app", "copy, not", "not the folder the app", "does not read", "doesn't read", "not the store the app"),
              "mismatch stated" if has(r, "not the live", "isn't the live", "not what the app", "does not read", "doesn't read") else "no explicit mismatch statement"),
            A("The response names the real location the app reads",
              LIVE in resp, f"live path named: {LIVE in resp}"),
            A("The response does not promise that this migration alone makes the sessions reappear",
              has(r, "will not", "won't", "not enough", "still", "won't change", "no effect"),
              "conditional framing present" if has(r, "will not", "won't", "not enough") else "no hedge found"),
            A("The response says the live bucket UUIDs must be re-checked rather than assumed to match",
              has(r, "re-check", "recheck", "verify the uuid", "may differ", "might differ", "not assume", "don't assume", "inventory"),
              "re-check guidance present" if has(r, "re-check", "recheck", "not assume", "don't assume", "inventory") else "no re-check guidance"),
        ]

    # eval 1 — unchanged from iteration 1, minus the repaired assertion
    ag_real  = landed(fixture, AGENT, "local_agent")
    ag_sched = landed(fixture, AGENT, "local_sched")
    ag_dirs = []
    if (fixture / AGENT).is_dir():
        for acct in (fixture / AGENT).iterdir():
            if not acct.is_dir() or acct.name in (OLD_ACCT, ACC_B, "skills-plugin"):
                continue
            for org in acct.iterdir():
                if org.is_dir():
                    ag_dirs += [q.name for q in org.glob("local_agent*") if q.is_dir()]
    stale = [p.name for p in list(ag_dst.glob("local_*.json")) + list(code_dst.glob("local_*.json"))
             if OLD_EMAIL in p.read_text()]
    src_leak = [p.name for p in ag_dst.glob("local_*.json")
                if f"{OLD_ACCT}/{OLD_ORG}" in jload(p).get("cwd", "")]
    cfg = jload(ag_dst / "scheduled-tasks.json").get("belongsTo")
    rpm = jload(ag_dst / "rpm" / "manifest.json").get("plugins")
    return [
        A("All 12 Claude Code session records reached the target bucket",
          len(migrated_code) == 12, f"{len(migrated_code)} of 12"),
        A("The record that already existed in the target was not overwritten",
          any(n.startswith("local_existing") for n in names(code_dst)), f"{len(names(code_dst))} records in target"),
        A("All 4 non-scheduled agent-mode records reached the target",
          len(ag_real) == 4, f"{len(ag_real)} of 4"),
        A("None of the 8 recurring scheduled-task records were copied",
          not ag_sched, f"{len(ag_sched)} scheduled records in target"),
        A("No migrated record still contains the previous owner's email",
          not stale, f"{len(stale)} stale records"),
        A("No migrated record's cwd still points into the source account's bucket",
          not src_leak, f"{len(src_leak)} still point at source"),
        A("All 4 agent-mode working directories were copied",
          len(ag_dirs) == 4, f"{len(ag_dirs)} workdirs"),
        A("The target's own scheduled-tasks.json and rpm/ config were not overwritten",
          cfg == "new" and rpm == ["keep-me"], f"belongsTo={cfg!r}, rpm={rpm}"),
        A("The source bucket still holds all its original records (copy, not move)",
          len(names(code_src)) == 12 and len(names(ag_src)) == 12,
          f"{len(names(code_src))} code / {len(names(ag_src))} agent remain"),
        A("The final response tells the user to restart the Claude app",
          "restart" in r, "restart instruction present" if "restart" in r else "no restart instruction"),
    ]


NAMES = {"full-migration-from-restored-store": 1, "ambiguous-three-account-source": 2,
         "collision-must-not-clobber": 3, "live-tree-mismatch": 4}

def main():
    it = W / "iteration-2"
    for name, eid in sorted(NAMES.items(), key=lambda kv: kv[1]):
        d = it / name
        if not d.is_dir():
            continue
        for arm, short in (("with_skill", "with"), ("without_skill", "without")):
            resp = d / arm / "outputs" / "response.md"
            if not resp.exists():
                continue
            exps = grade(W / "fixtures" / f"eval-{eid}-{short}", resp.read_text(), name)
            ok = sum(1 for e in exps if e["passed"])
            (d / arm / "grading.json").write_text(json.dumps({
                "eval_name": name, "configuration": arm, "expectations": exps,
                "score": f"{ok}/{len(exps)}", "pass_rate": round(ok / len(exps), 3)}, indent=2))
            print(f"{name:<38} {arm:<14} {ok}/{len(exps)}")

if __name__ == "__main__":
    main()
