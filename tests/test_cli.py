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
        "claim-check ✓ test · pytest -q · 3 passed in 0.1s"


def test_failing_run(session):
    session.bash("pytest -q | tail -1", "1 failed, 2 passed in 0.1s")
    assert stop(session, "테스트 모두 통과.") == \
        "claim-check ✗ test · pytest -q · 1 failed, 2 passed in 0.1s"


def test_failing_run_then_edits(session, project):
    session.bash("pytest", "", exit_code=1)
    session.edit(str(project / "src/a.py"))
    assert stop(session, "Fixed; tests pass.", project) == \
        "claim-check ✗ test · pytest · exit code 1, then 1 file (src/a.py) changed"


def test_stale_run(session, project):
    session.bash("pytest", "4 passed")
    for name in ("a", "b", "c", "d", "a"):
        session.edit(str(project / f"src/{name}.py"))
    assert stop(session, "All tests pass.", project) == \
        "claim-check ⚠ test · pytest · 4 passed, then 4 files (src/a.py, src/b.py +2) changed"


def test_no_run(session):
    session.bash("npm run build")
    assert stop(session, "Tests pass and the build succeeds.") == "\n".join([
        "claim-check ⚠ test · no run",
        "claim-check ✓ build · npm run build · passed",
    ])


def test_unknown_and_empty(session):
    session.bash("pytest; echo done", "done")
    session.bash("npx tsc --noEmit | head", "")
    assert stop(session, "Tests pass. Type check passes.") == "\n".join([
        "claim-check ⚠ test · pytest · unknown: exit code hidden by a pipe or ;",
        "claim-check ⚠ lint · tsc --noEmit · unknown: exit code hidden by a pipe or ;",
    ])
    session.bash("pytest -k nothing", "collected 3 items / 3 deselected\nno tests ran", exit_code=5)
    assert stop(session, "Tests pass.") == \
        "claim-check ✗ test · pytest -k nothing · no tests ran"
    session.bash("npx vitest run", "No test files found, exiting with code 1", exit_code=1)
    assert stop(session, "Tests pass.") == "claim-check ✗ test · vitest run · No test files found, exiting with code 1"


def test_subagent_run_is_labelled(session):
    session.prompt("go")
    session.subagent().bash("pytest", "2 passed")
    assert stop(session, "Tests pass.") == \
        "claim-check ✓ test · pytest (subagent) · 2 passed"


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
    assert " · pytest " + "x" * 32 + "… · passed" in text


def test_report_one_file_and_relative_paths():
    run = Run("build", "make", "pass", None, seq=1)
    edit = Edit("/p/src/a.py", seq=2)
    text = report.line(Claim("build", "Build succeeds."), Session([run], [edit]), cwd="/p")
    assert text == "claim-check ⚠ build · make · passed, then 1 file (src/a.py) changed"


def hook(stdin):
    return subprocess.run([sys.executable, "-I", str(BIN), "hook", "stop"], input=stdin,
                          capture_output=True, text=True, check=True)


def test_hook_entry_point(session):
    session.bash("pytest", "", exit_code=1)
    out = hook(json.dumps({"transcript_path": str(session.path), "last_assistant_message": "All tests pass."}))
    assert json.loads(out.stdout)["systemMessage"].startswith("claim-check ✗ test · pytest · exit code 1")
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
    assert capsys.readouterr().out.startswith("claim-check ✓ test · pytest · 1 passed")
    assert cli.main(["check", str(session.path), "--message", "Nothing to see."]) == 0
    assert capsys.readouterr().out == "claim-check: no test, build, lint, commit, push or tag claims in the message\n"


def test_cwd_filters_edits_outside_the_project(session, project):
    session.bash("pytest", "1 passed")
    session.edit("/elsewhere/a.py")
    assert stop(session, "Tests pass.", project).startswith('claim-check ✓')


def test_report_boundaries():
    run = Run("test", "p" * 40, "pass", None, seq=1)
    assert " · " + "p" * 40 + " · passed" in report.line(Claim("test", "Tests pass."), Session([run], []))
    edits = [Edit("/abs/a.py", seq=2), Edit("/abs/b.py", seq=3), Edit("/abs/c.py", seq=4)]
    text = report.line(Claim("test", "Tests pass."), Session([Run("test", "pytest", "pass", None, seq=1)], edits))
    assert "3 files (/abs/a.py, /abs/b.py +1) changed" in text


def run_hook(monkeypatch, capsys, stdin, event="stop"):
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    assert cli.main(["hook", event]) == 0
    return capsys.readouterr().out


def test_hook_in_process(session, monkeypatch, capsys):
    session.bash("pytest", "", exit_code=1)
    payload = {"transcript_path": str(session.path), "last_assistant_message": "테스트 통과 ✓"}
    out = run_hook(monkeypatch, capsys, json.dumps(payload))
    assert out.endswith("\n") and "claim-check ✗" in out  # not escaped
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


def test_claim_names_its_target(session, tmp_path):
    a, b = tmp_path / "deid-guard", tmp_path / "claim-check"
    session.bash(f"cd {a} && claude plugin test . 2>&1 | tail -3", " 34 pass\n 0 fail")
    session.bash(f"cd {b} && pytest -q", "1 failed in 0.1s", exit_code=1)
    assert stop(session, "deid-guard 테스트 34개 전부 통과.") == "claim-check ✓ test deid-guard · claude plugin test . · 34 pass"
    assert stop(session, "claim-check 테스트 통과.") == "claim-check ✗ test claim-check · pytest -q · 1 failed in 0.1s"
    assert stop(session, "All tests pass in src/x-y.py.").startswith("claim-check ✗ test · pytest -q")  # unknown name: last run
    session.bash(f"cd {tmp_path / 'deid-guard-old'} && pytest -q", "9 passed")
    assert stop(session, "deid-guard 테스트 통과.").startswith("claim-check ✓ test deid-guard · claude plugin test .")
    session.bash(f"cd {tmp_path / 'sw-qa'} && git commit -qm x")
    assert stop(session, "sw-qa 테스트 통과.") == "claim-check ⚠ test sw-qa · no run"


def test_claimed_count_must_match(session):
    session.bash("pytest -q", "12 passed in 0.1s")
    assert stop(session, "테스트 12개 통과.").startswith("claim-check ✓")
    assert stop(session, "All 14 tests pass.") == "claim-check ✗ test · pytest -q · 12 passed, claimed 14"


def test_action_claims(session, project):
    session.bash("git add -A && git commit -q -m fix", "")
    session.bash("git push origin main 2>&1 | tail -2", "To https://x/y.git\n   7811bed..963d9da  main -> main")
    assert stop(session, "Committed and pushed main.") == "\n".join([
        "claim-check ✓ commit · git commit -q -m fix · done",
        "claim-check ✓ push · git push origin main · 7811bed..963d9da  main -> main"])
    session.bash("git push origin v1 2>&1 | tail -1", "! [rejected]        v1 -> v1 (already exists)")
    assert stop(session, "태그 v1도 push했어.").startswith("claim-check ✗ push · git push origin v1 · ! [rejected]")
    assert stop(session, "태그 달았어.") == "claim-check ⚠ tag · no run"
    session.edit(str(project / "src/a.py"))
    assert stop(session, "커밋했어.", project) == "claim-check ⚠ commit · git commit -q -m fix · done, then 1 file (src/a.py) changed"
    session.bash("git -C ~/r -c credential.helper='!f(){ echo x; }; f' push origin main | tail -1", "   1..2  main -> main")
    assert stop(session, "Pushed main.") == \
        "claim-check ⚠ push · git push origin main · unknown: exit code hidden by a pipe or ;"  # -C, -c dropped


def test_target_staleness_and_pushed_tag(session, tmp_path):
    a = tmp_path / "deid-guard"
    session.bash(f"cd {a} && claude plugin test .", " 34 pass\n 0 fail")
    session.edit(str(tmp_path / "claim-check/src/x.py"))
    assert stop(session, "deid-guard 테스트 통과.", tmp_path).startswith("claim-check ✓")
    session.edit(str(a / "hooks/register.ts"))
    assert ", then 1 file (deid-guard/hooks/register.ts) changed" in stop(session, "deid-guard 테스트 통과.", tmp_path)
    session.bash(f"cd {a} && claude plugin tag .", "✔ Created tag deid-guard--v0.4.2")
    session.bash(f"cd {a} && git push origin main deid-guard--v0.4.2 2>&1 | tail -1", " * [new tag]  deid-guard--v0.4.2 -> deid-guard--v0.4.2")
    assert stop(session, "deid-guard--v0.4.2 push했고 태그도 올렸어.").startswith(
        "claim-check ✓ push+tag deid-guard--v0.4.2 · git push origin main deid-guard--v0.4.2 · * [new tag]")
    assert stop(session, "Tests pass. All tests pass. 테스트 통과.").startswith("claim-check ⚠ test ·")  # one verdict, one line
