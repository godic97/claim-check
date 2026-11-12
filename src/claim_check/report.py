"""Compare each claim with the last matching run and write the end-of-turn report."""

import os
import re

LABEL = {"test": "test", "build": "build", "lint": "lint/type-check", "commit": "commit", "push": "push", "tag": "tag"}
CHECKS = ("test", "build", "lint")  # a code change after the run makes it stale; for actions only a commit goes stale
MAX_FILES = 3
PASSED = re.compile(r"(\d+)\s+(?:passed|passing|pass)\b|Passed:\s*(\d+)")


def _command(command, limit=70):
    command = " ".join(command.split())
    return command if len(command) <= limit else command[:limit - 1] + "…"


def _files(edits, cwd):
    paths = []
    for edit in edits:
        path = edit.path
        if cwd and os.path.isabs(path):
            path = os.path.relpath(path, cwd)
        if path not in paths:
            paths.append(path)
    shown = ", ".join(paths[:MAX_FILES])
    if len(paths) > MAX_FILES:
        shown += f" and {len(paths) - MAX_FILES} more"
    return f"{len(paths)} file{'s' if len(paths) != 1 else ''} ({shown})"


def _names(run, target):
    """True when the run's directory or command names the target as a whole word: deid-guard, not deid-guard-old."""
    return re.search(rf"(?<![\w-]){re.escape(target)}(?![\w-])", f"{run.where} {run.command}", re.I) is not None


def _passed(detail):
    m = PASSED.search(detail or "")
    return int(m.group(1) or m.group(2)) if m else None


def line(claim, session, cwd=None):
    """One report line for one claim."""
    label = LABEL[claim.kind]
    quote = f'"{claim.quote}"'
    # Only names that some command in the session ran in or on narrow the match; other words stay prose.
    known = [t for t in claim.targets if any(_names(r, t) for r in session.runs)]
    kinds = {claim.kind, "push"} if claim.kind == "tag" and known else {claim.kind}  # pushing a named tag backs it
    runs = [r for r in session.runs if r.kind in kinds and (not known or any(_names(r, t) for t in known))]
    if not runs:
        scope = f" for {', '.join(known)}" if known else ""
        return f"claim-check ⚠ {quote} — no {label} command{scope} ran in this session"
    last = runs[-1]
    command = _command(last.command) + ("` in a subagent" if last.subagent else "`")
    passed = "passed" if claim.kind in CHECKS else "succeeded"
    later = [e for e in session.edits if e.seq > last.seq] if claim.kind in CHECKS + ("commit",) else []
    if known:  # a run picked by name goes stale only through edits to that name
        later = [e for e in later if any(re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", e.path, re.I) for t in known)]
    detail = f": {last.detail}" if last.detail else ""
    if last.outcome == "fail":
        text = f"claim-check ✗ {quote} — the last {label} run failed (`{command}{detail})"
        if later:
            text += f", and {_files(later, cwd)} changed after it without a re-run"
        return text
    if last.outcome == "empty":
        return f"claim-check ✗ {quote} — the last {label} run ran no tests (`{command}{detail})"
    if last.outcome == "unknown":
        return f"claim-check ⚠ {quote} — the result of the last {label} run is unknown (`{command}): {last.detail}"
    shown = _passed(last.detail)
    if claim.count is not None and shown is not None and shown != claim.count:
        return f"claim-check ✗ {quote} — the last {label} run shows {shown} passing, not {claim.count} (`{command}{detail})"
    if later:
        return f"claim-check ⚠ {quote} — {_files(later, cwd)} changed after the last {label} run (`{command}, {passed})"
    if claim.kind not in CHECKS:
        return f"claim-check ✓ {quote} — `{command} {passed}{detail}"
    return f"claim-check ✓ {quote} — `{command} passed{detail} and nothing changed after it"


def lines(claims, session, cwd=None):
    return list(dict.fromkeys(line(claim, session, cwd) for claim in claims))  # a push can back both push and tag
