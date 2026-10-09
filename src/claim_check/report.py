"""Compare each claim with the last matching run and write the end-of-turn report."""

import os

LABEL = {"test": "test", "build": "build", "lint": "lint/type-check"}
MAX_FILES = 3


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


def line(claim, session, cwd=None):
    """One report line for one claim."""
    label = LABEL[claim.kind]
    quote = f'"{claim.quote}"'
    runs = [r for r in session.runs if r.kind == claim.kind]
    if not runs:
        return f"claim-check ⚠ {quote} — no {label} command ran in this session"
    last = runs[-1]
    command = _command(last.command) + ("` in a subagent" if last.subagent else "`")
    later = [e for e in session.edits if e.seq > last.seq]
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
    if later:
        return f"claim-check ⚠ {quote} — {_files(later, cwd)} changed after the last {label} run (`{command}, passed)"
    return f"claim-check ✓ {quote} — `{command} passed{detail} and nothing changed after it"


def lines(claims, session, cwd=None):
    return [line(claim, session, cwd) for claim in claims]
