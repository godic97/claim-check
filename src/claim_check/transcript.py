"""Read a Claude Code session transcript: which checks ran, how they ended, and which files changed after."""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass

from . import commands

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_EXTENSIONS = {".md", ".markdown", ".rst", ".txt", ".adoc"}
CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".go", ".rs", ".java", ".kt", ".scala",
    ".cs", ".c", ".h", ".cc", ".cpp", ".hpp", ".rb", ".php", ".swift", ".json", ".toml", ".yaml", ".yml", ".cfg",
    ".ini", ".sh",
}
EXIT_CODE = re.compile(r"(?:Error: )?Exit code (\d+)")
SHELL_EDIT = re.compile(
    r"\bsed\s+(?:-\w+\s+)*-i|\bperl\s+-\w*i|\bpatch\s|"
    r"\bgit\s+(?:apply|checkout|switch|restore|stash|merge|rebase|pull|cherry-pick|reset|am|revert)\b")
# A script passed through a heredoc or `-c` that writes files.
PATH_LITERAL = re.compile(r"""(?:Path|open)\(\s*[rbf]?['"]([^'"]+)['"]""")
SCRIPT_WRITE = re.compile(r"\.write_(?:text|bytes)\(|\bopen\([^)\n]*,\s*['\"][wax]|\bwriteFileSync\(|\bsed\s+-i")


@dataclass
class Run:
    kind: str  # test | build | lint
    command: str  # the check itself: the simple command inside the Bash command, wrappers removed
    outcome: str  # pass | fail | empty | unknown
    detail: str | None  # the output's summary line, or why the outcome is unknown
    seq: int = 0  # position among the session's tool results, main session and subagents merged by time
    subagent: bool = False


@dataclass
class Edit:
    path: str
    seq: int = 0


@dataclass
class Session:
    runs: list
    edits: list


def _result_text(block, tool_result):
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    parts = [content if isinstance(content, str) else ""]
    if isinstance(tool_result, dict):
        parts += [str(tool_result.get("stdout") or ""), str(tool_result.get("stderr") or "")]
    return "\n".join(parts)


def _inside(path, cwd):
    if not cwd:
        return True
    root = os.path.realpath(cwd)
    full = os.path.realpath(os.path.join(root, path))
    return full == root or full.startswith(root + os.sep)


def _counts(path, cwd):
    """An edit makes earlier checks stale unless it is documentation or outside the project."""
    return bool(path) and os.path.splitext(path)[1].lower() not in DOC_EXTENSIONS and _inside(path, cwd)


def _code_inside(paths, here, cwd):
    return any(os.path.splitext(p)[1].lower() not in DOC_EXTENSIONS and _inside(os.path.join(here, p), cwd)
               for p in paths)


def _shell_edit(command, cwd):
    """A label for the edit when a shell command changes code inside the project, else None."""
    _, bodies = commands.split_heredocs(command)
    here = cwd or "."
    for seg in commands.segments(command):
        if seg.words[:1] == ["cd"] and len(seg.words) > 1:
            here = os.path.join(here, seg.words[1])
            continue
        written = [t for t in seg.writes if os.path.splitext(t)[1].lower() in CODE_EXTENSIONS]
        if _code_inside(written, here, cwd):
            return f"{written[0]} (shell redirect)"
        text = " ".join(seg.words)
        if SHELL_EDIT.search(text):
            files = [w for w in seg.words[1:] if not w.startswith("-") and re.search(r"\.\w+$", w)]
            if _code_inside(files, here, cwd) if files else _inside(here, cwd):
                return f"{files[-1]} ({seg.words[0]})" if files else f"`{text[:40]}`"
    # A script (heredoc or -c) that writes files: judge the file names it mentions, if any.
    scripts = [b for b in bodies if SCRIPT_WRITE.search(b)]
    scripts += [w for seg in commands.segments(command) if "-c" in seg.words
                for w in seg.words if SCRIPT_WRITE.search(w)]
    for script in scripts:
        named = PATH_LITERAL.findall(script)
        if _code_inside(named, here, cwd) if named else _inside(here, cwd):
            return f"{named[0]} (script)" if named else "a file written by a shell script"
    return None


def _bash(tool_input, block, tool_result, cwd, out):
    command = tool_input.get("command") or ""
    segs = commands.segments(command)
    checks = [(i, kind) for i, kind in ((i, commands.classify(s.words)) for i, s in enumerate(segs)) if kind]
    if not checks:
        label = None if block.get("is_error") else _shell_edit(command, cwd)
        if label:
            out.append(Edit(label))
        return
    output = _result_text(block, tool_result)
    exit_match = EXIT_CODE.match(output.strip())
    reason = None
    if tool_input.get("run_in_background"):
        reason = "it ran in the background, and its result is not in the transcript"
    elif isinstance(tool_result, dict) and tool_result.get("interrupted"):
        reason = "it was interrupted"
    elif block.get("is_error") and not exit_match:
        if not re.search(r"timed out", output, re.I):
            return  # never ran: permission denied or blocked by a hook
        reason = "it timed out"
    exit_code = int(exit_match.group(1)) if exit_match else 0
    for i, kind in checks:
        outcome, detail = ("unknown", reason) if reason else commands.outcome(segs, i, exit_code, output)
        out.append(Run(kind, " ".join(segs[i].words), outcome, detail))


def _entries(path, wanted):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if any(w in line for w in wanted):
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    yield entry


def _message(entry):
    message = entry.get("message")
    return message if isinstance(message, dict) else {}


def _blocks(entry):
    content = _message(entry).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _items(path, cwd, subagent):
    """(timestamp, Run or Edit) for every check run and code edit in one transcript file."""
    pending = {}
    stamp = ""
    for entry in _entries(path, ('"tool_use"', '"tool_result"')):
        stamp = entry.get("timestamp") or stamp
        for block in _blocks(entry):
            if block.get("type") == "tool_use":
                pending[block.get("id")] = (block.get("name"), block.get("input") or {})
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in pending:
                name, tool_input = pending.pop(block["tool_use_id"])
                found = []
                if name == "Bash":
                    _bash(tool_input, block, entry.get("toolUseResult"), cwd, found)
                elif name in EDIT_TOOLS and not block.get("is_error"):
                    path_ = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
                    if _counts(path_, cwd):
                        found.append(Edit(path_))
                for item in found:
                    if isinstance(item, Run):
                        item.subagent = subagent
                    yield stamp, item


def transcript_files(path):
    """The session transcript and its subagents' transcripts (<session>/subagents/*.jsonl)."""
    return [path] + sorted(glob.glob(os.path.join(os.path.splitext(path)[0], "subagents", "*.jsonl")))


def read(path, cwd=None):
    """Every check run and code edit in the session, subagents included, in time order."""
    items = []
    for n, file in enumerate(transcript_files(path)):
        items += [(stamp, n, i, item) for i, (stamp, item) in enumerate(_items(file, cwd, subagent=n > 0))]
    items.sort(key=lambda x: x[:3])
    session = Session([], [])
    for seq, (_, _, _, item) in enumerate(items, 1):
        item.seq = seq
        (session.runs if isinstance(item, Run) else session.edits).append(item)
    return session


def last_message(path):
    """The agent's text after the last user prompt (fallback when the hook input has no last_assistant_message)."""
    texts = []
    for entry in _entries(path, ('"user"', '"assistant"')):
        if entry.get("type") == "user":
            content = _message(entry).get("content")
            if isinstance(content, str) or (_blocks(entry) and all(b.get("type") == "text" for b in _blocks(entry))):
                texts = []  # a new prompt
        elif entry.get("type") == "assistant":
            texts += [b.get("text", "") for b in _blocks(entry) if b.get("type") == "text"]
    return "\n".join(texts)
