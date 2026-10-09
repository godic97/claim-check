import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

START = datetime(2026, 10, 9, tzinfo=timezone.utc)


class Transcript:
    """Writes a Claude Code session transcript (.jsonl) the way the harness records it."""

    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.lines = []
        self.n = 0
        self.clock = clock if clock is not None else [0]

    def _stamp(self):
        self.clock[0] += 1
        return (START + timedelta(seconds=self.clock[0])).isoformat().replace("+00:00", "Z")

    def _add(self, entry):
        entry.setdefault("timestamp", self._stamp())
        self.lines.append(json.dumps(entry, ensure_ascii=False))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self.lines) + "\n")

    def prompt(self, text):
        self._add({"type": "user", "message": {"role": "user", "content": text}})

    def say(self, text):
        self._add({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})

    def tool(self, name, tool_input, content, is_error=False, tool_result=None):
        self.n += 1
        tid = f"toolu_{self.n}"
        self._add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        block = {"type": "tool_result", "tool_use_id": tid, "content": content}
        if is_error:
            block["is_error"] = True
        self._add({"type": "user", "message": {"role": "user", "content": [block]}, "toolUseResult": tool_result})

    def bash(self, command, output="", exit_code=0, **extra):
        tool_input = {"command": command, **{k: v for k, v in extra.items() if k == "run_in_background"}}
        result = {"stdout": output, "stderr": "", "interrupted": bool(extra.get("interrupted"))}
        if exit_code:
            text = f"Exit code {exit_code}\n{output}"
            self.tool("Bash", tool_input, text, is_error=True, tool_result=f"Error: {text}")
        else:
            self.tool("Bash", tool_input, output, tool_result=result)

    def edit(self, file_path, tool="Edit", is_error=False):
        self.tool(tool, {"file_path": file_path}, "ok" if not is_error else "String not found", is_error=is_error)

    def subagent(self, name="agent-a1"):
        return Transcript(self.path.with_suffix("") / "subagents" / f"{name}.jsonl", clock=self.clock)


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "proj"
    path.mkdir()
    return path


@pytest.fixture
def session(tmp_path):
    return Transcript(tmp_path / "sessions" / "s1.jsonl")
