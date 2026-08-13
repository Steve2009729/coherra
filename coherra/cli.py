"""Coherra CLI.

Entry point: `coherra` console script (defined in pyproject.toml).

Commands:
  coherra health              -- last audit summary (score + issue count)
  coherra scan                -- run a full audit now, print results
  coherra issues              -- list every flagged issue from the last scan
  coherra fix <issue_id>      -- apply a repair (interactive for contradictions)
  coherra fix --all           -- batch-apply all safe repairs
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

# Respect NO_COLOR env var (https://no-color.org/) and non-TTY pipes
_COLOR_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR", "") == ""


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI escape sequence, or return plain text if color is off."""
    if not _COLOR_ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def red(t: str)    -> str: return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def green(t: str)  -> str: return _c("32", t)
def cyan(t: str)   -> str: return _c("36", t)
def bold(t: str)   -> str: return _c("1",  t)
def dim(t: str)    -> str: return _c("2",  t)
def white(t: str)  -> str: return _c("97", t)


def _sev_color(sev: str, text: str) -> str:
    return {
        "contradiction": red(text),
        "duplicate":     yellow(text),
        "stale":         dim(text),
    }.get(sev, text)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_SEV_LABEL = {
    "contradiction": "CONTRADICT",
    "duplicate":     "DUPLICATE ",
    "stale":         "STALE     ",
}
_SEV_ORDER = {"contradiction": 0, "duplicate": 1, "stale": 2}


def _health_bar(score: int | float) -> str:
    """Colorized ASCII progress bar for the health score (0–100)."""
    score = int(score)
    filled = score // 5          # 20 segments total
    bar    = "█" * filled + "░" * (20 - filled)

    if score >= 80:
        colored_bar = green(bar)
        emoji = green("✓")
    elif score >= 50:
        colored_bar = yellow(bar)
        emoji = yellow("!")
    else:
        colored_bar = red(bar)
        emoji = red("✗")

    return f"{colored_bar} {bold(str(score))}/100  {emoji}"


def _print_issues_table(issues: list[dict[str, Any]]) -> None:
    """Print issues in a clean grouped table, color-coded by severity."""
    if not issues:
        print(f"  {green('(none)')}")
        return

    sorted_issues = sorted(
        issues,
        key=lambda i: (
            _SEV_ORDER.get(i.get("severity", ""), 99),
            i.get("category", ""),
            i.get("name", ""),
        ),
    )

    current_sev = None
    for issue in sorted_issues:
        sev     = issue.get("severity", "unknown")
        label   = _SEV_LABEL.get(sev, sev.upper()[:10].ljust(10))
        cat     = issue.get("category", "")
        name    = issue.get("name", "")
        iid     = issue.get("id", "?")[:10]
        related = issue.get("related_entity", "")

        # Group header on severity change
        if sev != current_sev:
            current_sev = sev
            heading = {
                "contradiction": red("── Contradictions ──"),
                "duplicate":     yellow("── Duplicates ──"),
                "stale":         dim("── Stale ──"),
            }.get(sev, f"── {sev} ──")
            print(f"\n  {heading}")

        tag  = _sev_color(sev, f"[{label}]")
        addr = bold(f"{cat}/{name}")
        print(f"  {tag}  {addr}")

        if related:
            val_a = issue.get("value_a", "")
            val_b = issue.get("value_b", "")
            if val_a or val_b:
                print(f"            {dim('A:')} {white(repr(val_a))}  {dim('vs')}  {dim('B:')} {white(repr(val_b))}")
            print(f"            {dim('↔')}  {related}")
        else:
            detail = issue.get("detail", "")
            if detail:
                print(f"            {dim(detail)}")

        print(f"            {dim('id:')} {cyan(iid)}")

    print()


# ---------------------------------------------------------------------------
# coherra health
# ---------------------------------------------------------------------------

def cmd_health(_args: argparse.Namespace) -> int:
    """Show the last stored audit result."""
    from .client import open_client

    client = open_client()
    result = client.get_state("coherra:last_audit")

    if result is None:
        print(f"{yellow('no audits run yet')} — try: {bold('coherra scan')}")
        return 0

    body       = result.get("body", result)
    timestamp  = body.get("timestamp", result.get("updated_at", ""))
    score      = body.get("health_score", "?")
    issues     = body.get("issues_found", [])
    n_entities = body.get("entity_count", "?")

    # One-line summary banner
    if isinstance(score, (int, float)):
        s = int(score)
        if s >= 80:
            status = green(f"HEALTHY ({s}/100)")
        elif s >= 50:
            status = yellow(f"DEGRADED ({s}/100)")
        else:
            status = red(f"CRITICAL ({s}/100)")
    else:
        status = str(score)

    print(f"\n  {bold('Coherra Memory Health')}  ·  {dim(timestamp)}")
    print(f"  {'Health ':10s}: {_health_bar(score) if isinstance(score, (int, float)) else score}")
    print(f"  {'Entities':10s}: {n_entities}")
    print(f"  {'Issues  ':10s}: {bold(str(len(issues)))}  {dim('(' + status + ')')}")

    if issues:
        by_sev: dict[str, int] = {}
        for i in issues:
            s2 = i.get("severity", "unknown")
            by_sev[s2] = by_sev.get(s2, 0) + 1

        parts = []
        for sev, color_fn in (("contradiction", red), ("duplicate", yellow), ("stale", dim)):
            n = by_sev.get(sev, 0)
            if n:
                parts.append(color_fn(f"{n} {sev}{'s' if n > 1 else ''}"))
        if parts:
            print(f"  {'':10s}  {',  '.join(parts)}")
        print()
        print(f"  {dim('Run')} {bold('coherra issues')} {dim('for details  ·')}  {bold('coherra scan')} {dim('to refresh')}")
    print()
    return 0


# ---------------------------------------------------------------------------
# coherra scan
# ---------------------------------------------------------------------------

def cmd_scan(_args: argparse.Namespace) -> int:
    """Run a full audit now and print results."""
    from .audit import run_audit

    print(f"\n  {bold('Running Coherra audit…')}")
    result    = run_audit()
    score     = result.get("health_score", 0)
    issues    = result.get("issues_found", [])
    timestamp = result.get("timestamp", "")
    n_ent     = result.get("entity_count", 0)

    print(f"  {dim('Scanned')}   : {timestamp}")
    print(f"  {dim('Entities')}  : {n_ent}")
    print(f"  {dim('Health')}    : {_health_bar(score)}")
    print(f"  {dim('Issues')}    : {bold(str(len(issues)))}")

    if issues:
        _print_issues_table(issues)
        by_sev: dict[str, int] = {}
        for i in issues:
            sv = i.get("severity", "")
            by_sev[sv] = by_sev.get(sv, 0) + 1
        parts = []
        if by_sev.get("contradiction"):
            parts.append(red(f"{by_sev['contradiction']} contradiction(s) — need manual resolution"))
        if by_sev.get("duplicate"):
            parts.append(yellow(f"{by_sev['duplicate']} duplicate(s)"))
        if by_sev.get("stale"):
            parts.append(dim(f"{by_sev['stale']} stale"))
        print(f"  {dim('Next:')}  {bold('coherra issues')}  ·  {bold('coherra fix --all')} {dim('(safe repairs)')}")
    else:
        print(f"\n  {green('✓ No issues — memory is clean.')}")

    print(f"\n  {dim('Results saved to coherra:last_audit.')}\n")
    return 0


# ---------------------------------------------------------------------------
# coherra issues
# ---------------------------------------------------------------------------

def cmd_issues(args: argparse.Namespace) -> int:
    """List all issues from the last audit scan."""
    from .client import open_client

    client = open_client()
    result = client.get_state("coherra:last_audit")

    if result is None:
        print(f"{yellow('No audit data')} — run {bold('coherra scan')} first.")
        return 1

    body   = result.get("body", result)
    issues = body.get("issues_found", [])

    sev_filter = getattr(args, "severity", None)
    if sev_filter:
        issues = [i for i in issues if i.get("severity") == sev_filter]

    timestamp = body.get("timestamp", "")
    score     = body.get("health_score", "?")

    print(f"\n  {bold('Coherra Issues')}  ·  last scan: {dim(timestamp)}  ·  health: {bold(str(score))}/100")
    print(f"  Showing {bold(str(len(issues)))} issue(s)" +
          (f" (filtered: {sev_filter})" if sev_filter else "") + "\n")

    _print_issues_table(issues)

    if not sev_filter and any(i.get("severity") == "contradiction" for i in issues):
        print(f"  {red('Contradictions require manual resolution:')}  {bold('coherra fix <id>')}")
        print(f"  {dim('Safe repairs (duplicates + stale):')}        {bold('coherra fix --all')}\n")

    return 0


# ---------------------------------------------------------------------------
# coherra fix
# ---------------------------------------------------------------------------

def _prompt_contradiction(issue: dict[str, Any]) -> tuple[str, Any]:
    """Interactive prompt for contradiction resolution. Returns (action, value)."""
    cat_a  = issue.get("category", "")
    name_a = issue.get("name", "")
    ref_b  = issue.get("related_entity", "")
    val_a  = issue.get("value_a", "")
    val_b  = issue.get("value_b", "")
    iid    = issue.get("id", "")[:10]

    print(f"\n  {bold('Contradiction')}  {dim('id:')} {cyan(iid)}")
    print(f"  {red('A')}  {bold(cat_a + '/' + name_a)}  =  {white(repr(val_a))}")
    print(f"  {red('B')}  {bold(ref_b)}                =  {white(repr(val_b))}")
    print()
    print(f"  {dim('a')}           keep A, archive B")
    print(f"  {dim('b')}           keep B, archive A")
    print(f"  {dim('m <value>')}   merge: archive both, write canonical value")
    print(f"  {dim('s')}           skip")
    print()

    while True:
        raw = input("  Choice: ").strip()
        if not raw:
            continue
        if raw.lower() == "a":
            return "keep_a", None
        if raw.lower() == "b":
            return "keep_b", None
        if raw.lower() == "s":
            return "skip", None
        if raw.lower().startswith("m "):
            new_val = raw[2:].strip()
            if new_val:
                return "merge_manual", new_val
            print(f"  {yellow('Provide a value after m, e.g.:  m Python')}")
            continue
        print(f"  {yellow('Enter a, b, m <value>, or s')}")


def cmd_fix(args: argparse.Namespace) -> int:
    """Apply one repair or batch-apply safe repairs."""
    from .repair import apply_repair, apply_safe_repairs
    from .client import open_client

    # ------------------------------------------------------------------
    # --all  →  batch safe repairs
    # ------------------------------------------------------------------
    if getattr(args, "all", False):
        print(f"\n  {bold('Applying safe repairs')} {dim('(stale + duplicates; contradictions skipped)…')}\n")
        results = apply_safe_repairs()
        ok      = [r for r in results if r.get("ok")]
        failed  = [r for r in results if not r.get("ok")]

        if not results:
            print(f"  {green('Nothing to repair')} — no stale or duplicate issues in last scan.")
            return 0

        for r in ok:
            sev  = r.get("severity", "")
            act  = r.get("action_taken", "")
            iid  = r.get("issue_id", "")[:10]
            arch = ", ".join(r.get("archived", []))
            kept = ", ".join(r.get("written", []))
            tick = green("✓")
            sev_str = _sev_color(sev, sev)
            print(f"  {tick} [{sev_str}]  {dim(act):10s}  {cyan(iid)}")
            if arch:
                print(f"      {dim('archived:')} {arch}")
            if kept:
                print(f"      {dim('kept:')}     {kept}")

        for r in failed:
            print(f"  {red('✗')} [{r.get('severity','?')}]  {r.get('issue_id','?')[:10]}  {red(r.get('error','?'))}")

        print()
        if ok:
            print(f"  {green(str(len(ok)))} fixed, {red(str(len(failed))) if failed else '0'} failed.")
            print(f"  {dim('Run')} {bold('coherra scan')} {dim('to refresh the health score.')}\n")
        return 0 if not failed else 1

    # ------------------------------------------------------------------
    # coherra fix <issue_id> [action]  →  single repair
    # ------------------------------------------------------------------
    issue_id = getattr(args, "issue_id", None)
    if not issue_id:
        print(f"  {yellow('Usage:')} coherra fix <issue_id> [action]  {dim('or')}  coherra fix --all")
        return 1

    action = getattr(args, "action", None)

    # Look up the issue
    client = open_client()
    state  = client.get_state("coherra:last_audit")
    audit_body = state.get("body", state) if state else {}
    issue = next(
        (i for i in audit_body.get("issues_found", []) if i.get("id") == issue_id),
        None,
    )

    if issue is None:
        print(f"  {red('Issue')} {cyan(issue_id)} {red('not found')} in last audit.")
        print(f"  Run {bold('coherra scan')} first, or check the id with {bold('coherra issues')}.")
        return 1

    severity = issue.get("severity", "")

    # Contradiction with no pre-supplied action → interactive prompt
    if severity == "contradiction" and not action:
        action, value = _prompt_contradiction(issue)
        if action == "skip":
            print(f"  {dim('Skipped.')}")
            return 0
    else:
        value = getattr(args, "value", None)
        if not action:
            defaults = {"stale": "archive", "duplicate": "merge"}
            action   = defaults.get(severity)
            if not action:
                print(f"  {yellow('Please supply an action for severity=')} {repr(severity)}")
                print(f"  stale:         archive | refresh")
                print(f"  duplicate:     merge")
                print(f"  contradiction: keep_a | keep_b | merge_manual <value>")
                return 1

    try:
        r = apply_repair(issue_id, action, value=value)
    except (KeyError, ValueError) as e:
        print(f"  {red('Repair failed:')} {e}")
        return 1

    sev   = r.get("severity", "")
    act   = r.get("action_taken", "")
    arch  = r.get("archived", [])
    wrote = r.get("written", [])

    print(f"\n  {green('✓')} Repaired {_sev_color(sev, '[' + sev + ']')}  {dim('action:')} {bold(act)}")
    if arch:
        print(f"  {dim('archived :')} {', '.join(arch)}")
    if wrote:
        print(f"  {dim('written  :')} {', '.join(wrote)}")
    print(f"  {dim('Run')} {bold('coherra scan')} {dim('to refresh the health score.')}\n")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coherra",
        description="Coherra — structured memory auditor for Sibyl Memory.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p_health = sub.add_parser("health", help="Show last audit summary.")
    p_health.set_defaults(func=cmd_health)

    p_scan = sub.add_parser("scan", help="Run a full audit now.")
    p_scan.set_defaults(func=cmd_scan)

    p_issues = sub.add_parser("issues", help="List flagged problems from last scan.")
    p_issues.add_argument(
        "--severity", choices=["contradiction", "duplicate", "stale"],
        help="Filter by severity.",
    )
    p_issues.set_defaults(func=cmd_issues)

    p_fix = sub.add_parser("fix", help="Apply a repair.")
    p_fix.add_argument("issue_id", nargs="?", help="Issue ID to fix.")
    p_fix.add_argument("action",   nargs="?",
                       help="archive|refresh (stale), merge (duplicate), "
                            "keep_a|keep_b|merge_manual (contradiction).")
    p_fix.add_argument("--value",     help="Canonical value for merge_manual.")
    p_fix.add_argument("--all",       action="store_true", help="Fix all safe issues.")
    p_fix.add_argument("--safe-only", action="store_true", help="(implied by --all)")
    p_fix.set_defaults(func=cmd_fix)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
