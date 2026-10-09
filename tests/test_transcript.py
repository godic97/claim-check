import json

from claim_check.transcript import last_message, read, transcript_files


def runs(session_, cwd=None):
    return [(r.kind, r.command, r.outcome, r.detail) for r in read(session_.path, cwd).runs]


def edits(session_, cwd=None):
    return [e.path for e in read(session_.path, cwd).edits]


def test_runs_with_outcome(session, project):
    session.bash("pytest -q", "3 passed in 0.1s")
    session.bash("cd x && npm run build", "", exit_code=1)
    session.bash("ls -la", "total 0")
    assert runs(session) == [
        ("test", "pytest -q", "pass", "3 passed in 0.1s"),
        ("build", "npm run build", "fail", "exit code 1"),
    ]


def test_permission_denied_or_blocked_command_never_ran(session):
    session.tool("Bash", {"command": "pytest"}, "Permission to use Bash has been denied.", is_error=True)
    assert runs(session) == []


def test_timeout_background_and_interrupt_are_unknown(session):
    session.tool("Bash", {"command": "pytest"}, "Command timed out after 2m 0.0s", is_error=True)
    session.bash("npm test", "Command running in background with ID: b1", run_in_background=True)
    session.bash("cargo test", "", interrupted=True)
    assert [(r[0], r[2], r[3]) for r in runs(session)] == [
        ("test", "unknown", "it timed out"),
        ("test", "unknown", "it ran in the background, and its result is not in the transcript"),
        ("test", "unknown", "it was interrupted"),
    ]


def test_result_content_as_blocks(session):
    session.tool("Bash", {"command": "pytest | tail -1"}, [{"type": "text", "text": "1 failed in 0.1s"}])
    assert runs(session)[0][2:] == ("fail", "1 failed in 0.1s")


def test_unmatched_results_and_bad_lines_are_skipped(session):
    session.lines.append('{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "nope"}]}}')
    session.lines.append('{not json "tool_use"')
    session.bash("pytest", "1 passed")
    assert len(runs(session)) == 1


def test_edit_tools_count_inside_the_project(session, project):
    session.edit(str(project / "src/a.py"))
    session.edit(str(project / "nb.ipynb"), tool="NotebookEdit")
    session.edit("src/b.py", tool="Write")
    session.edit(str(project / "README.md"))  # documentation
    session.edit("/elsewhere/c.py")  # outside the project
    session.edit(str(project / "src/d.py"), is_error=True)  # the edit failed
    session.tool("NotebookEdit", {"notebook_path": str(project / "x.ipynb")}, "ok")
    assert edits(session, str(project)) == [str(project / "src/a.py"), str(project / "nb.ipynb"), "src/b.py",
                                            str(project / "x.ipynb")]


def test_without_cwd_every_non_doc_edit_counts(session):
    session.edit("/elsewhere/c.py")
    session.edit("/elsewhere/c.md")
    assert edits(session) == ["/elsewhere/c.py"]


def test_shell_edits(session, project):
    session.bash("sed -i '' 's/a/b/' src/a.py")
    session.bash("sed -i '' 's/a/b/' /tmp/scratch/x.py")  # outside the project
    session.bash("cat > src/new.py <<'EOF'\nx = 1\nEOF")
    session.bash("echo hi > notes.log")  # not code
    session.bash("S=/tmp/scratch; cat > $S/t.py <<'EOF'\nx\nEOF")  # variable points outside
    session.bash("cd /tmp/scratch && echo x > a.py")  # after cd outside
    session.bash("git checkout main")
    session.bash("python - <<'EOF'\nfrom pathlib import Path\nPath('src/c.py').write_text('x')\nEOF")
    session.bash("python - <<'EOF'\nfrom pathlib import Path\nPath('README.md').write_text('x')\nEOF")
    session.bash("python - <<'EOF'\nopen(p, 'w').write(s)\nEOF")  # no file name: judged by directory
    session.bash("python -c \"open('src/d.py', 'w').write('x')\"")
    session.bash("cd /tmp/s && python - <<'EOF'\nopen(p, 'w').write(s)\nEOF")
    session.bash("sed -i '' 's/a/b/' src/e.py", exit_code=1)  # failed
    assert edits(session, str(project)) == [
        "src/a.py (sed)",
        "src/new.py (shell redirect)",
        "`git checkout main`",
        "src/c.py (script)",
        "a file written by a shell script",
        "src/d.py (script)",
    ]


def test_check_command_is_not_an_edit(session, project):
    session.bash("sed -i '' 's/a/b/' src/a.py && pytest", "1 passed")
    assert edits(session, str(project)) == []
    assert runs(session)[0][:3] == ("test", "pytest", "pass")


def test_subagent_runs_merge_by_time(session):
    session.bash("pytest", "1 passed")
    sub = session.subagent()
    sub.edit("src/a.py")
    sub.bash("pytest", "", exit_code=1)
    session.bash("npm run build")
    result = read(session.path)
    assert [(r.kind, r.outcome, r.subagent, r.seq) for r in result.runs] == [
        ("test", "pass", False, 1), ("test", "fail", True, 3), ("build", "pass", False, 4)]
    assert [(e.path, e.seq) for e in result.edits] == [("src/a.py", 2)]
    assert transcript_files(str(session.path)) == [str(session.path), str(sub.path)]


def test_last_message_is_the_text_after_the_last_prompt(session):
    session.prompt("first")
    session.say("old answer")
    session.prompt("second")
    session.say("Working.")
    session.bash("pytest", "1 passed")
    session.say("All tests pass.")
    assert last_message(session.path) == "Working.\nAll tests pass."


def test_last_message_prompt_as_text_blocks(session):
    session.say("old")
    session._add({"type": "user", "message": {"content": [{"type": "text", "text": "again"}]}})
    session.say("new")
    assert last_message(session.path) == "new"


def test_output_from_tool_result_stdout_and_stderr(session):
    session.tool("Bash", {"command": "pytest | tail -1"}, "", tool_result={"stdout": "2 passed in 0.1s"})
    session.tool("Bash", {"command": "pytest | tail -1"}, "", tool_result={"stdout": "", "stderr": "1 failed"})
    session.tool("Bash", {"command": "pytest | tail -1"}, None, tool_result=None)
    assert [r[2:] for r in runs(session)] == [
        ("pass", "2 passed in 0.1s"), ("fail", "1 failed"),
        ("unknown", "its exit status went through a pipe, `||` or `;`, and the output has no summary line")]


def test_result_blocks_join_with_newlines(session):
    session.tool("Bash", {"command": "pytest | tail -2"}, [{"type": "text", "text": "== 1 failed in 0.1s"},
                                                            {"type": "text", "text": "more"}, "junk"])
    assert runs(session)[0][3] == "1 failed in 0.1s"


def test_more_shell_edits(session, project):
    session.bash("cd src && sed -i '' 's/a/b/' a.py")
    session.bash("cd; sed -i '' 's/a/b/' b.py")
    session.bash("sed -i.bak 's/a/b/' README.md")  # the backup suffix is not a file
    session.bash("cd /tmp/x && git checkout main")
    session.bash("git checkout feature/a-very-long-branch-name-1234567890")
    session.bash("python - <<'EOF'\nopen('/tmp/x.py', 'w').write('x')\nEOF")
    assert edits(session, str(project)) == [
        "a.py (sed)", "b.py (sed)", "`git checkout feature/a-very-long-branch-`"]


def test_invalid_utf8_and_missing_timestamps(tmp_path):
    path = tmp_path / "s.jsonl"
    use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                         "input": {"command": "pytest"}}]}}
    result = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
    path.write_bytes(b'{"type": "x", "bad": "\xff"}\n' + json.dumps(use).encode() + b"\n" + json.dumps(result).encode())
    sub = tmp_path / "s" / "subagents" / "a.jsonl"
    sub.parent.mkdir(parents=True)
    use["message"]["content"][0]["id"] = "t2"
    result["message"]["content"][0]["tool_use_id"] = "t2"
    sub.write_text("\n".join(json.dumps(dict(e, timestamp="2026-10-09T00:00:01Z")) for e in (use, result)))
    assert [r.subagent for r in read(path).runs] == [False, True]


def test_non_object_lines_are_skipped(session):
    session.lines.append('["tool_use", "tool_result"]')
    session.lines.append('{"type": "user", "message": "tool_result as a string"}')
    session.lines.append('{"type": "assistant", "message": ["tool_use"]}')
    session.bash("pytest", "1 passed")
    session.say("All tests pass.")
    assert runs(session) == [("test", "pytest", "pass", "1 passed")]
    assert last_message(session.path) == "All tests pass."
