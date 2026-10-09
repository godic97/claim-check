import pytest

from claim_check.commands import classify, outcome, segments, split_heredocs


def kind(command):
    return [classify(s.words) for s in segments(command)]


@pytest.mark.parametrize("command, expected", [
    ("pytest -q", "test"),
    (".venv/bin/python -m pytest tests/", "test"),
    ("uv run python -m pytest", "test"),
    ("poetry run pytest", "test"),
    ("python3 -m unittest discover", "test"),
    ("timeout 600 pytest", "test"),
    ("FOO=1 env BAR=2 pytest", "test"),
    ("npx vitest run", "test"),
    ("./node_modules/.bin/jest", "test"),
    ("npm test", "test"),
    ("npm t", "test"),
    ("npm run test:unit", "test"),
    ("pnpm test", "test"),
    ("pnpm vitest", "test"),
    ("yarn jest --ci", "test"),
    ("bun test", "test"),
    ("go test ./...", "test"),
    ("cargo test", "test"),
    ("cargo nextest run", "test"),
    ("mvn -q test", "test"),
    ("./mvnw verify", "test"),
    ("./gradlew test", "test"),
    ("gradle :app:test", "test"),
    ("gradle check", "test"),
    ("dotnet test", "test"),
    ("sbt testOnly a.B", "test"),
    ("make test", "test"),
    ("deno test", "test"),
    ("swift test", "test"),
    ("mix test", "test"),
    ("python tests/run_all.py", "test"),
    ("python3 $S/test_outfit.py", "test"),
    ("node --test", "test"),
    ("node src/app.test.js", "test"),
    ("claude plugin test .", "test"),
    ("tsc --noEmit", "lint"),
    ("npx tsc --noEmit -p .", "lint"),
    ("ruff check .", "lint"),
    ("uvx pyflakes app.py", "lint"),
    ("mypy src", "lint"),
    ("cargo clippy", "lint"),
    ("cargo check", "lint"),
    ("go vet ./...", "lint"),
    ("npm run lint", "lint"),
    ("pnpm typecheck", "lint"),
    ("make lint", "lint"),
    ("deno check main.ts", "lint"),
    ("tsc", "build"),
    ("npm run build", "build"),
    ("pnpm build", "build"),
    ("cargo build --release", "build"),
    ("go build ./...", "build"),
    ("mvn package", "build"),
    ("gradle assemble", "build"),
    ("gradle compileJava", "build"),
    ("dotnet build", "build"),
    ("sbt compile", "build"),
    ("make", "build"),
    ("make -j8 all", "build"),
    ("cmake --build build", "build"),
    ("vite build", "build"),
    ("next build", "build"),
    ("python -m build", "build"),
    ("python3 -m py_compile a.py", "build"),
    ("swift build", "build"),
])
def test_classify(command, expected):
    assert kind(command)[-1] == expected


@pytest.mark.parametrize("command", [
    "pytest --version", "ruff --version", "pytest --collect-only", "cargo test --no-run", "jest --listTests",
    "python app.py", "npm install", "pnpm install", "git status", "echo pytest", "make install", "cmake ..",
    "mvn clean", "gradle clean", "sbt clean", "vite", "go run .", "cargo run", "mutation-gate test src/a.py",
    "npm run dev", "", "dotnet run", "mix compile",
])
def test_not_a_check(command):
    assert not any(kind(command))


def test_segments_split_on_operators_outside_quotes():
    segs = segments('cd x && pytest -k "a or b|c" | tail -5; echo "done && ok"')
    assert [s.words for s in segs] == [["cd", "x"], ["pytest", "-k", "a or b|c"], ["tail", "-5"], ["echo", "done && ok"]]
    assert [s.op_after for s in segs] == ["&&", "|", ";", ""]


def test_segments_newlines_and_trailing_separator():
    segs = segments("pytest\nnpm test\n")
    assert [s.op_after for s in segs] == [";", ""]
    assert [s.op_after for s in segments("pytest;")] == [""]
    assert [s.op_after for s in segments("pytest &")] == ["&"]
    assert [s.op_after for s in segments("pytest || true")] == ["||", ""]
    assert [s.op_after for s in segments("pytest |& tee log")] == ["|", ""]


def test_segments_skip_heredoc_bodies():
    command = "python - <<'EOF'\nimport pytest\nmake test\nEOF\nnpm test"
    assert kind(command) == [None, "test"]
    line, bodies = split_heredocs(command)
    assert line == "python - <<'EOF'\nnpm test"
    assert bodies == ["import pytest\nmake test"]


def test_split_heredocs_variants():
    assert split_heredocs("cat <<EOF > a.py\nx = 1\nEOF")[1] == ["x = 1"]
    assert split_heredocs('cat <<-"END"\n  y\n  END\npytest') == ('cat <<-"END"\npytest', ["  y"])
    assert split_heredocs("cat <<<'here string'\npytest") == ("cat <<<'here string'\npytest", [])


def test_segments_expand_variables_set_earlier():
    segs = segments("S=/tmp/x; F=$S/tests/t.py; python ${F}")
    assert segs[-1].words == ["python", "/tmp/x/tests/t.py"]
    assert segments("python $UNSET/t.py")[0].words == ["python", "$UNSET/t.py"]


def test_segments_record_redirect_targets():
    segs = segments("cat > src/a.py; echo hi >> log.txt 2>&1; ls &> all.log; sort < in.txt")
    assert [s.writes for s in segs] == [["src/a.py"], ["log.txt"], ["all.log"], []]
    assert segs[1].words == ["echo", "hi"]  # the `2` of `2>&1` is dropped


def test_segments_drop_shell_keywords_and_groups():
    assert kind("for d in a b; do pytest $d; done") == [None, "test"]
    assert kind("if true; then npm test; fi") == [None, "test"]
    assert kind("(cd engine && pytest)") == [None, "test"]
    assert kind("{ pytest; }") == ["test"]


def test_unbalanced_quotes_fall_back_to_whitespace():
    assert kind("pytest -k 'oops && npm run build") == ["test", "build"]


def check(command, exit_code=0, output=""):
    segs = segments(command)
    i = next(i for i, s in enumerate(segs) if classify(s.words))
    return outcome(segs, i, exit_code, output)


def test_outcome_from_exit_code():
    assert check("pytest") == ("pass", None)
    assert check("pytest", 0, "5 passed in 0.1s") == ("pass", "5 passed in 0.1s")
    assert check("pytest", 1) == ("fail", "exit code 1")
    assert check("cd x && pytest && echo ok", 2) == ("fail", "exit code 2")


def test_outcome_exit_code_beats_markers():
    assert check("pytest", 0, "log: 3 errors caught\n12 passed") == ("pass", "12 passed")
    assert check("pytest", 1, "== 1 failed, 2 passed in 0.2s ==") == ("fail", "1 failed, 2 passed in 0.2s")
    assert check("go test ./...", 1, "--- FAIL: TestX\nok  \tother") == ("fail", "FAIL: TestX")
    assert check("pytest", 127, "bash: pytest: command not found") == ("fail", "bash: pytest: command not found")
    assert check("pytest | tail -1", 0, "bash: pytest: command not found")[0] == "fail"
    assert check("npx jest --passWithNoTests", 0, "No tests found, exiting with code 0")[0] == "empty"


def test_outcome_masked_exit_status_uses_output():
    assert check("pytest | tail -1", 0, "3 passed in 1s") == ("pass", "3 passed in 1s")
    assert check("pytest | tail -1", 0, "1 failed in 1s") == ("fail", "1 failed in 1s")
    assert check("pytest; echo done", 0, "done")[0] == "unknown"
    assert check("pytest || true", 0, "")[0] == "unknown"


def test_outcome_no_tests_ran():
    assert check("pytest", 5, "collected 0 items\nno tests ran") == ("empty", "collected 0 items")
    assert check("npx vitest run", 1, "No test files found, exiting with code 1")[0] == "empty"


@pytest.mark.parametrize("output, expected", [
    ("test result: ok. 3 passed", "pass"),
    ("test result: FAILED. 1 passed; 1 failed", "fail"),
    ("BUILD SUCCESS", "pass"),
    ("BUILD FAILURE", "fail"),
    ("src/a.ts(1,1): error TS2304: Cannot find name", "fail"),
    ("error[E0425]: cannot find value", "fail"),
    ("Passed!  - Failed: 0, Passed: 4", "pass"),
    ("Failed!  - Failed: 1, Passed: 3", "fail"),
    ("All checks passed!", "pass"),
    ("Success: no issues found in 3 source files", "pass"),
    ("Found 2 errors in 1 file", "fail"),
    ("0 errors, 0 warnings", "pass"),
    ("Ran 4 tests in 0.1s\n\nOK", "pass"),
    ("FAILED (failures=1)", "fail"),
    ("Tests:       4 passed, 4 total", "pass"),
    ("Compiled successfully", "pass"),
    ("✓ built in 1.2s", "pass"),
    ("npm ERR! Test failed.", "fail"),
    ("ok  \texample.com/shop\t0.3s", "pass"),
])
def test_outcome_markers_when_masked(output, expected):
    assert check("make test | tail -3", 0, output)[0] == expected


def test_outcome_several_checks_in_one_command():
    command = "pytest -k a | tail -1; pytest | tail -1"
    segs = segments(command)
    output = "2 failed, 53 deselected in 0.1s\n55 passed in 5.8s"
    assert outcome(segs, 0, 0, output) == ("fail", "2 failed, 53 deselected in 0.1s")
    assert outcome(segs, 2, 0, output) == ("pass", "55 passed in 5.8s")
    # One summary line for two checks: nobody knows whose it is.
    assert outcome(segs, 2, 0, "55 passed in 5.8s")[0] == "unknown"


def test_outcome_nonzero_exit_with_a_later_check():
    segs = segments("npm run build && npm test")
    assert outcome(segs, 0, 1, "")[0] == "unknown"
    assert outcome(segs, 2 - 1, 1, "") == ("fail", "exit code 1")
    assert outcome(segs, 0, 0, "") == ("pass", None)


@pytest.mark.parametrize("command, expected", [
    ("yarn test", "test"),
    ("bun build ./index.ts", "build"),
    ("yarn tsc --noEmit", "lint"),
    ("pnpm vite build", "build"),
    ("pnpm next build", "build"),
    ("pnpm eslint .", "lint"),
    ("yarn webpack", "build"),
    ("python -u tests/test_a.py", "test"),
    ("deno lint", "lint"),
    ("mvn install", "test"),
    ("mvn compile", "build"),
    ("mvn test-compile", "build"),
    ("gradle :test", "test"),
    ("gradle build", "build"),
    ("make tests", "test"),
    ("make check", "test"),
    ("make typecheck", "lint"),
    ("make build", "build"),
    ("make CC=gcc", "build"),
    ("pytest \\\n  -q", "test"),
])
def test_classify_more(command, expected):
    assert kind(command)[-1] == expected


@pytest.mark.parametrize("command", ["npm run", "npm install test-utils", "npm jest", "node app.js", "claude -p hi"])
def test_not_a_check_more(command):
    assert not any(kind(command))


def test_segment_details():
    assert segments("pytest \\\n  -k XML")[0].words == ["pytest", "-k", "XML"]
    assert segments("pytest >& out.log")[0].words == ["pytest"]
    assert segments("cat > ~/x.py")[0].writes[0].endswith("/x.py")
    assert not segments("cat > ~/x.py")[0].writes[0].startswith("~")
    assert segments("A=b=c; echo $A")[0].words == ["echo", "b=c"]
    assert segments("echo x >&2")[0].writes == []
    assert segments("echo x &>> all.log")[0].writes == ["all.log"]
    assert segments("cat <<<'x' > a.py")[0].writes == ["a.py"]


def test_assignment_segments_keep_the_masking_operator():
    assert [s.op_after for s in segments("pytest; X=1 && npm test")] == [";", ""]
    assert [s.op_after for s in segments("pytest && X=1; npm test")] == [";", ""]
    assert [s.op_after for s in segments("pytest && X=1 && npm test")] == ["&&", ""]


def test_split_heredocs_unterminated():
    assert split_heredocs("cat <<EOF\nabc") == ("cat <<EOF", ["abc"])


def test_outcome_group_and_earlier_pipes_do_not_mask():
    assert check("(cd x && pytest)") == ("pass", None)
    assert check("ls | wc -l; pytest") == ("pass", None)
    assert check("ls | wc -l; pytest", 1) == ("fail", "exit code 1")


def test_outcome_summary_is_cut_at_100_characters():
    status, summary = check("pytest", 1, "1 failed " + "x" * 200)
    assert status == "fail" and len(summary) == 100


def test_outcome_three_checks_two_summary_lines_each():
    segs = segments("make lint | tail -1; pytest | tail -1; npm run build | tail -1")
    output = "0 errors\n2 passed\n1 failed"
    checks = [i for i, s in enumerate(segs) if classify(s.words)]
    assert [outcome(segs, i, 0, output)[0] for i in checks] == ["pass", "unknown", "fail"]
    output = "0 errors\n1 failed\nBuild succeeded"
    assert outcome(segs, checks[-1], 0, output) == ("pass", "Build succeeded")


def test_more_package_manager_scripts():
    assert kind("yarn build") == ["build"]
    assert kind("bun lint") == ["lint"]


def test_unknown_message_depends_on_masking_after_the_check():
    segs = segments("ls | wc -l; npm run build && npm test")
    assert outcome(segs, 2, 1, "") == ("unknown", "exit code 1 could come from a later command in the same line")


@pytest.mark.parametrize("command", [
    "caffeinate -s pytest -q", "nice -n 10 pytest", "nice pytest", "timeout -s KILL 60 pytest",
    "timeout --kill-after=5 60 pytest", "time -p pytest", "gtimeout -k 5 60 pytest",
])
def test_wrapper_options(command):
    assert kind(command) == ["test"]
    assert segments(command)[0].words[0] == "pytest"


@pytest.mark.parametrize("command", ["make -n test", "make --just-print check", "make -q build", "make --dry-run lint"])
def test_make_dry_runs_are_not_checks(command):
    assert kind(command) == [None]


def test_outcome_unmasked_chain_does_not_guess_whose_summary():
    segs = segments("npm run build && npm test")
    assert outcome(segs, 0, 0, "Compiled successfully\nNo tests found") == ("pass", None)
    assert outcome(segs, 1, 1, "src/a.ts(1,1): error TS1: x") == ("fail", "exit code 1")
