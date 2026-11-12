"""Compare each claim with the last matching run and write the end-of-turn report."""

import os
import re

CHECKS = ("test", "build", "lint")  # a code change after the run makes it stale; for actions only a commit goes stale
MAX_FILES = 2
PASSED = re.compile(r"(\d+)\s+(?:passed|passing|pass)\b|Passed:\s*(\d+)")


def _command(command, limit=40):
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
        shown += f" +{len(paths) - MAX_FILES}"
    return f"{len(paths)} file{'s' if len(paths) != 1 else ''} ({shown})"


def _names(run, target):
    """True when the run's directory or command names the target as a whole word: deid-guard, not deid-guard-old."""
    return re.search(rf"(?<![\w-]){re.escape(target)}(?![\w-])", f"{run.where} {run.command}", re.I) is not None


def _passed(detail):
    m = PASSED.search(detail or "")
    return int(m.group(1) or m.group(2)) if m else None


def _judge(claim, session, cwd):
    """(mark, names the claim was matched by, "<command> · <result>" or "no run")."""
    # Only names that some command in the session ran in or on narrow the match; other words stay prose.
    known = [t for t in claim.targets if any(_names(r, t) for r in session.runs)]
    kinds = {claim.kind, "push"} if claim.kind == "tag" and known else {claim.kind}  # pushing a named tag backs it
    runs = [r for r in session.runs if r.kind in kinds and (not known or any(_names(r, t) for t in known))]
    if not runs:
        return "⚠", known, "no run"
    last = runs[-1]
    later = [e for e in session.edits if e.seq > last.seq] if claim.kind in CHECKS + ("commit",) else []
    if known:  # a run picked by name goes stale only through edits to that name
        later = [e for e in later if any(re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", e.path, re.I) for t in known)]
    then = f", then {_files(later, cwd)} changed" if later else ""
    command = _command(last.command) + (" (subagent)" if last.subagent else "")

    def out(mark, result):
        return mark, known, f"{command} · {result}"

    if last.outcome == "fail":
        return out("✗", (last.detail or "failed") + then)
    if last.outcome == "empty":
        return out("✗", last.detail or "no tests ran")
    if last.outcome == "unknown":
        return out("⚠", f"unknown: {last.detail}")
    shown = _passed(last.detail)
    if claim.count is not None and shown is not None and shown != claim.count:
        return out("✗", f"{shown} passed, claimed {claim.count}")
    done = last.detail or ("passed" if claim.kind in CHECKS else "done")
    return out("⚠", done + then) if later else out("✓", done)


def _format(mark, kinds, names, rest):
    return f"claim-check {mark} {' '.join(['+'.join(kinds)] + list(names))} · {rest}"


def line(claim, session, cwd=None):
    """One report line: `claim-check <mark> <kind> [<names>] · <command> · <result>`."""
    mark, names, rest = _judge(claim, session, cwd)
    return _format(mark, [claim.kind], names, rest)


def lines(claims, session, cwd=None):
    """One line per verdict: claims judged the same way share it (`push+tag`, `test` said twice)."""
    groups = {}
    for claim in claims:
        mark, names, rest = _judge(claim, session, cwd)
        kinds = groups.setdefault((mark, tuple(names), rest), [])
        if claim.kind not in kinds:
            kinds.append(claim.kind)
    return [_format(mark, kinds, names, rest) for (mark, names, rest), kinds in groups.items()]
