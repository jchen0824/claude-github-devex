#!/usr/bin/env python3
"""Grade migrate-claude-sessions eval runs by inspecting fixture post-state."""
import json, sys
from pathlib import Path

W = Path(__file__).resolve().parent
OLD_ACCT, OLD_ORG = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
NEW_ACCT, NEW_ORG = "cccccccc-3333-4333-8333-cccccccccccc", "dddddddd-4444-4444-8444-dddddddddddd"
OLD_EMAIL = "previous.owner@example.com"
CODE, AGENT = "claude-code-sessions", "local-agent-mode-sessions"


def bucket(root, store, acct, org):
    return root / store / acct / org


def names(d, pat="local_*.json"):
    return sorted(p.name for p in d.glob(pat)) if d.is_dir() else []


def jload(p):
    try: return json.loads(p.read_text())
    except Exception: return {}


def A(text, passed, evidence):
    return {"text": text, "passed": bool(passed), "evidence": evidence}


def grade(fixture: Path, response: str, kind: str, run: Path | None = None):
    code_src = bucket(fixture, CODE, OLD_ACCT, OLD_ORG)
    code_dst = bucket(fixture, CODE, NEW_ACCT, NEW_ORG)
    ag_src = bucket(fixture, AGENT, OLD_ACCT, OLD_ORG)
    ag_dst = bucket(fixture, AGENT, NEW_ACCT, NEW_ORG)

    code_migrated = [n for n in names(code_dst) if n.startswith("local_code")]
    ag_real = [n for n in names(ag_dst) if n.startswith("local_agent")]
    ag_sched = [n for n in names(ag_dst) if n.startswith("local_sched")]
    ag_dirs = sorted(p.name for p in ag_dst.glob("local_agent*")) if ag_dst.is_dir() else []
    ag_dirs = [d for d in ag_dirs if (ag_dst / d).is_dir()]

    stale = []
    for p in list(ag_dst.glob("local_*.json")) + list(code_dst.glob("local_*.json")):
        if OLD_EMAIL in p.read_text():
            stale.append(p.name)

    repointed, unresolved = [], []
    for p in ag_dst.glob("local_*.json"):
        cwd = jload(p).get("cwd", "")
        if isinstance(cwd, str) and f"{NEW_ACCT}/{NEW_ORG}" in cwd:
            repointed.append(p.name)
            if not Path(cwd).is_dir():
                unresolved.append(cwd)
    src_leak = [p.name for p in ag_dst.glob("local_*.json")
                if f"{OLD_ACCT}/{OLD_ORG}" in jload(p).get("cwd", "")]

    def config_intact():
        ok, ev = True, []
        st = ag_dst / "scheduled-tasks.json"
        if st.exists():
            v = jload(st).get("belongsTo")
            ev.append(f"agent scheduled-tasks.json belongsTo={v!r}")
            ok &= (v == "new")
        rpm = ag_dst / "rpm" / "manifest.json"
        if rpm.exists():
            v = jload(rpm).get("plugins")
            ev.append(f"rpm/manifest.json plugins={v}")
            ok &= (v == ["keep-me"])
        return ok, "; ".join(ev) or "no config files found in target"

    cfg_ok, cfg_ev = config_intact()
    rl = response.lower()

    if kind == "diagnosis-without-premature-migration":
        pristine = {str(p.relative_to(W / "fixtures/_pristine"))
                    for p in (W / "fixtures/_pristine").rglob("*")}
        actual = {str(p.relative_to(fixture)) for p in fixture.rglob("*")}
        added, removed = actual - pristine, pristine - actual
        return [
            A("No files were added, removed, or migrated anywhere in the fixture (the user said not to change anything)",
              not added and not removed,
              f"{len(added)} added, {len(removed)} removed" +
              (f"; e.g. {sorted(added)[:3]}" if added else "")),
            A("The response explains that sessions are partitioned by directory path under accountUuid/organizationUuid",
              ("accountuuid" in rl or "account uuid" in rl or "<account" in rl)
              and ("organizationuuid" in rl or "org" in rl) and "director" in rl,
              "response references account/org directory partitioning"
              if "accountuuid" in rl else "no clear path-scoping explanation found"),
            A("The response states the sessions still exist on disk and were not deleted",
              any(k in rl for k in ["not gone", "not deleted", "still on disk", "still there",
                                    "nothing was lost", "not lost", "still exist", "hasn't been deleted",
                                    "isn't gone", "intact"]),
              "reassurance language present" if "not " in rl else "no explicit reassurance found"),
            A("The response reports what is actually in the buckets, including the previous account's identity",
              OLD_EMAIL in response and ("12" in response),
              f"previous owner email cited: {OLD_EMAIL in response}; bucket counts cited: {'12' in response}"),
        ]

    out = [
        A("All 4 non-scheduled agent-mode session records are present in the target bucket",
          len(ag_real) == 4, f"{len(ag_real)} found: {ag_real}"),
        A("None of the 8 recurring scheduled-task records were copied into the target bucket",
          len(ag_sched) == 0, f"{len(ag_sched)} scheduled records in target"),
        A("No migrated record still contains the previous owner's email address",
          not stale, f"{len(stale)} records still contain {OLD_EMAIL}" + (f": {stale[:3]}" if stale else "")),
        A("No migrated record's cwd still points into the source account's bucket",
          not src_leak, f"{len(src_leak)} records still point at the source bucket"),
        A("Rewritten cwd values resolve to directories that exist (assumes the migration completes in this tree, not a stage-then-install flow)",
          len(repointed) == 2 and not unresolved,
          f"{len(repointed)} rewritten into target, {len(unresolved)} do not resolve"),
        A("All 4 agent-mode working directories were copied",
          len(ag_dirs) == 4, f"{len(ag_dirs)} workdirs: {ag_dirs}"),
        A("The target bucket's own scheduled-tasks.json and rpm/ config were not overwritten", cfg_ok, cfg_ev),
    ]

    if kind == "full-migration-from-restored-store":
        backup = [p.name for p in fixture.rglob("*.tar.gz")]
        if run:
            backup += [p.name for p in run.rglob("*.tar.gz")]
            backup += [p.name for p in run.rglob("*backup*") if p.is_dir()]
        out = [
            A("All 12 Claude Code session records from the source bucket are present in the target bucket",
              len(code_migrated) == 12, f"{len(code_migrated)} of 12 in target"),
            A("The session record that already existed in the target bucket is still present (not overwritten)",
              any(n.startswith("local_existing") for n in names(code_dst)),
              f"target code records: {len(names(code_dst))}"),
        ] + out + [
            A("The source bucket still holds all its original records (copy, not move)",
              len(names(code_src)) == 12 and len(names(ag_src)) == 12,
              f"source: {len(names(code_src))} code, {len(names(ag_src))} agent (expected 12/12)"),
            A("A backup was taken before any files were written",
              bool(backup) or "backup" in rl,
              f"artifacts: {backup[:3]}" if backup else "no artifact; response mentions backup: " + str("backup" in rl)),
            A("The final response tells the user to restart the Claude app",
              "restart" in rl, "'restart' present in response" if "restart" in rl else "no restart instruction"),
        ]
    elif kind == "agent-mode-identity-and-paths":
        out.insert(1, A("The Claude Code store was left alone (target code bucket still holds only its pre-existing record)",
                        len(code_migrated) == 0,
                        f"{len(code_migrated)} code records leaked into target (expected 0)"))
    return out


def main():
    it = W / "iteration-1"
    for eval_dir in sorted(p for p in it.iterdir() if p.is_dir()):
        for arm, n in (("with_skill", "with"), ("without_skill", "without")):
            run = eval_dir / arm
            resp = run / "outputs" / "response.md"
            if not resp.exists():
                continue
            eid = {"full-migration-from-restored-store": 1,
                   "diagnosis-without-premature-migration": 2,
                   "agent-mode-identity-and-paths": 3}[eval_dir.name]
            fixture = W / "fixtures" / f"eval-{eid}-{n}"
            exps = grade(fixture, resp.read_text(), eval_dir.name, run)
            passed = sum(1 for e in exps if e["passed"])
            (run / "grading.json").write_text(json.dumps({
                "eval_name": eval_dir.name, "configuration": arm,
                "expectations": exps,
                "score": f"{passed}/{len(exps)}",
                "pass_rate": round(passed / len(exps), 3),
            }, indent=2))
            print(f"{eval_dir.name:<40} {arm:<14} {passed}/{len(exps)}")


if __name__ == "__main__":
    main()
