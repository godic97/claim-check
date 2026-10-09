import io
import json
import subprocess
import sys
from pathlib import Path

from claim_check import cli, report
from claim_check.claims import Claim
from claim_check.transcript import Edit, Run, Session

BIN = Path(__file__).resolve().parent.parent / "bin" / "claim-check"


def stop(session_, message, cwd=None):
    payload = {"transcript_path": str(session_.path), "last_assistant_message": message}
    if cwd:
        payload["cwd"] = str(cwd)
    result = cli.on_stop(payload)
    return result["systemMessage"] if result else None


def test_no_claim_no_report(session):
    session.bash("pytest", "", exit_code=1)
    assert stop(session, "I changed the parser.") is None


def test_passing_run(session):
    session.bash("pytest -q", "3 passed in 0.1s")
    assert stop(session, "All tests pass.") == \
        'claim-check ✓ "All tests pass." — `pytest -q` passed: 3 passed in 0.1s and nothing changed after it'


def test_failing_run(session):
    session.bash("pytest -q | tail -1", "1 failed, 2 passed in 0.1s")
    assert stop(session, "테스트 모두 통과.") == \
        'claim-check ✗ "테스트 모두 통과." — the last test run failed (`pytest -q`: 1 failed, 2 passed in 0.1s)'


def test_failing_run_then_edits(session, project):
    session.bash("pytest", "", exit_code=1)
    session.edit(str(project / "src/a.py"))
    assert stop(session, "Fixed; tests pass.", project) == (
        'claim-check ✗ "Fixed; tests pass." — the last test run failed (`pytest`: exit code 1), '
        "and 1 file (src/a.py) changed after it without a re-run")


def test_stale_run(session, project):
    session.bash("pytest", "4 passed")
    for name in ("a", "b", "c", "d", "a"):
        session.edit(str(project / f"src/{name}.py"))
    assert stop(session, "All tests pass.", project) == (
        'claim-check ⚠ "All tests pass." — 4 files (src/a.py, src/b.py, src/c.py and 1 more) '
        "changed after the last test run (`pytest`, passed)")


def test_no_run(session):
    session.bash("npm run build")
    assert stop(session, "Tests pass and the build succeeds.") == "\n".join([
        'claim-check ⚠ "Tests pass and the build succeeds." — no test command ran in this session',
        'claim-check ✓ "Tests pass and the build succeeds." — `npm run build` passed and nothing changed after it',
    ])


def test_unknown_and_empty(session):
    session.bash("pytest; echo done", "done")
    session.bash("npx tsc --noEmit | head", "")
    assert stop(session, "Tests pass. Type check passes.") == "\n".join([
        'claim-check ⚠ "Tests pass." — the result of the last test run is unknown (`pytest`): '
        "its exit status went through a pipe, `||` or `;`, and the output has no summary line",
        'claim-check ⚠ "Type check passes." — the result of the last lint/type-check run is unknown (`tsc --noEmit`): '
        "its exit status went through a pipe, `||` or `;`, and the output has no summary line",
    ])
    session.bash("pytest -k nothing", "collected 3 items / 3 deselected\nno tests ran", exit_code=5)
    assert stop(session, "Tests pass.") == \
        'claim-check ✗ "Tests pass." — the last test run ran no tests (`pytest -k nothing`: no tests ran)'


def test_subagent_run_is_labelled(session):
    session.prompt("go")
    session.subagent().bash("pytest", "2 passed")
    assert stop(session, "Tests pass.") == \
        'claim-check ✓ "Tests pass." — `pytest` in a subagent passed: 2 passed and nothing changed after it'


def test_message_falls_back_to_transcript(session):
    session.prompt("go")
    session.bash("pytest", "", exit_code=1)
    session.say("All tests pass.")
    result = cli.on_stop({"transcript_path": str(session.path)})
    assert result["systemMessage"].startswith("claim-check ✗")


def test_missing_transcript():
    assert cli.on_stop({"last_assistant_message": "All tests pass."}) is None
    assert cli.on_stop({"transcript_path": "/nonexistent.jsonl", "last_assistant_message": "All tests pass."}) is None


def test_report_shortens_long_commands():
    run = Run("test", "pytest " + "x" * 100, "pass", None, seq=1)
    text = report.line(Claim("test", "Tests pass."), Session([run], []))
    assert "`pytest " + "x" * 62 + "…` passed" in text


def test_report_one_file_and_relative_paths():
    run = Run("build", "make", "pass", None, seq=1)
    edit = Edit("/p/src/a.py", seq=2)
    text = report.line(Claim("build", "Build succeeds."), Session([run], [edit]), cwd="/p")
    assert text == 'claim-check ⚠ "Build succeeds." — 1 file (src/a.py) changed after the last build run (`make`, passed)'


def hook(stdin):
    return subprocess.run([sys.executable, "-I", str(BIN), "hook", "stop"], input=stdin,
                          capture_output=True, text=True, check=True)


def test_hook_entry_point(session):
    session.bash("pytest", "", exit_code=1)
    out = hook(json.dumps({"transcript_path": str(session.path), "last_assistant_message": "All tests pass."}))
    assert json.loads(out.stdout)["systemMessage"].startswith('claim-check ✗ "All tests pass."')
    assert hook(json.dumps({"transcript_path": str(session.path), "last_assistant_message": "Done."})).stdout == ""


def test_hook_internal_error_is_reported():
    out = hook("not json")
    message = json.loads(out.stdout)["systemMessage"]
    assert message.startswith("claim-check internal error (stop): ") and "JSONDecodeError" in message


def test_check_command(session, capsys):
    session.prompt("go")
    session.bash("pytest", "1 passed")
    session.say("All tests pass.")
    assert cli.main(["check", str(session.path)]) == 0
    assert capsys.readouterr().out.startswith('claim-check ✓ "All tests pass."')
    assert cli.main(["check", str(session.path), "--message", "Nothing to see."]) == 0
    assert capsys.readouterr().out == "claim-check: no test, build or lint claims in the message\n"


def test_cwd_filters_edits_outside_the_project(session, project):
    session.bash("pytest", "1 passed")
    session.edit("/elsewhere/a.py")
    assert stop(session, "Tests pass.", project).startswith('claim-check ✓')


def test_report_boundaries():
    run = Run("test", "p" * 70, "pass", None, seq=1)
    assert "`" + "p" * 70 + "` passed" in report.line(Claim("test", "Tests pass."), Session([run], []))
    edits = [Edit("/abs/a.py", seq=2), Edit("/abs/b.py", seq=3), Edit("/abs/c.py", seq=4)]
    text = report.line(Claim("test", "Tests pass."), Session([Run("test", "pytest", "pass", None, seq=1)], edits))
    assert "3 files (/abs/a.py, /abs/b.py, /abs/c.py) changed" in text


def run_hook(monkeypatch, capsys, stdin, event="stop"):
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    assert cli.main(["hook", event]) == 0
    return capsys.readouterr().out


def test_hook_in_process(session, monkeypatch, capsys):
    session.bash("pytest", "", exit_code=1)
    payload = {"transcript_path": str(session.path), "last_assistant_message": "테스트 통과 ✓"}
    out = run_hook(monkeypatch, capsys, json.dumps(payload))
    assert out.endswith("\n") and "테스트 통과 ✓" in out  # not escaped
    assert json.loads(out) == {"systemMessage": cli.on_stop(payload)["systemMessage"]}
    payload["last_assistant_message"] = "Done."
    assert run_hook(monkeypatch, capsys, json.dumps(payload)) == ""


def test_hook_in_process_error(monkeypatch, capsys):
    out = json.loads(run_hook(monkeypatch, capsys, "[1"))
    assert out["systemMessage"].startswith("claim-check internal error (stop): json.decoder.JSONDecodeError: ")


def test_check_command_with_cwd(session, project, capsys):
    session.prompt("go")
    session.bash("pytest", "1 passed")
    session.edit("/elsewhere/a.py")
    session.say("All tests pass.")
    assert cli.main(["check", str(session.path), "--cwd", str(project)]) == 0
    assert capsys.readouterr().out.startswith('claim-check ✓')
    session.bash("npm run build")
    session.bash("pytest", "1 passed")
    assert cli.main(["check", str(session.path), "--message", "Build succeeds. Tests pass."]) == 0
    assert capsys.readouterr().out.count("\n") == 2
