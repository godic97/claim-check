# claim-check

Checks an AI coding agent's success claims against what actually ran.

When Claude ends a turn with "all tests pass", "the build succeeds" or "lint is clean", claim-check looks up the last matching command in the session transcript and reports, under the answer, whether that command backs the claim:

```
claim-check ✓ "All tests pass." — `pytest -q` passed: 12 passed in 0.41s and nothing changed after it
claim-check ✗ "테스트 모두 통과." — the last test run failed (`pytest -q`: 1 failed, 11 passed in 0.40s)
claim-check ⚠ "Pytest passes and the docstring is in." — 1 file (m.py) changed after the last test run (`pytest -q`, passed)
claim-check ⚠ "The build succeeds." — no build command ran in this session
```

The report is for you, not for Claude. claim-check never blocks a turn and never asks Claude to do anything. It reads the transcript on your machine and sends nothing anywhere.

claim-check is part of [Gingoa](https://github.com/godic97/Gingoa).

## What it checks

**Claims.** At the end of each turn, the Stop hook reads Claude's final message and looks for three kinds of claims, in English and Korean:

| Kind | Examples |
|---|---|
| test | "All tests pass", "the suite is green", "12 passed", "테스트 모두 통과", "테스트 149개가 통과했습니다" |
| build | "the build succeeds", "it compiles cleanly", "빌드 성공", "컴파일 오류 없음" |
| lint / type check | "mypy reports no errors", "no lint errors", "타입 체크 통과", "린트 깨끗함" |

Negations, conditions, plans, questions and quotes are not claims: "tests don't pass yet", "if the tests pass", "tests should pass now", "do the tests pass?", "테스트가 통과하지 않았습니다", "통과 여부 확인 필요", "테스트 통과 예상", text in code blocks, `>` quotes and quoted phrases. Mixed results such as "3 passed, 1 failed" or "21개 중 20개 통과" are reports of a failure, not claims of success.

**Evidence.** For each claim, claim-check finds the last command of the same kind in the session, subagents included. It recognizes the usual runners: pytest, unittest, tox, vitest, jest, mocha, `npm`/`pnpm`/`yarn`/`bun` scripts, `go test`, `cargo test`, Maven, Gradle, `dotnet test`, sbt, make, `tsc`, ESLint, Ruff, flake8, pyflakes, mypy, pyright, clippy, `go vet` and others, through wrappers like `uv run`, `npx`, `timeout` and `python -m`.

The outcome comes from the command's exit code, which Claude Code records with every Bash call, and from the tool's own summary line ("1 failed", "BUILD FAILURE", "error TS2304", "test result: ok", ...). When the exit code is hidden (`pytest | tail -5`, `pytest; echo done`), only the summary line counts.

**Verdicts.**

| | Meaning |
|---|---|
| ✓ | The last run passed and no code changed after it. |
| ✗ | The last run failed, or it ran no tests. |
| ⚠ | No such command ran in this session; code changed after the last passing run; or the outcome is unknown (exit code hidden by a pipe and no summary line, run in the background, interrupted, timed out). |

Code changes are Edit/Write/NotebookEdit calls and shell commands that write code files (`sed -i`, `> file.py`, scripts that write files, `git checkout`, ...). Documentation (`.md`, `.txt`, `.rst`) and files outside the project do not count.

## Install

```
claude plugin marketplace add godic97/claim-check
claude plugin install claim-check@claim-check
```

Inside Claude Code, the same works as `/plugin marketplace add …` followed by `/plugin install …`. Requires Python 3.8 or later; no other dependencies.

## Checking a past session

```
bin/claim-check check ~/.claude/projects/<project>/<session>.jsonl
bin/claim-check check <session>.jsonl --message "All tests pass." --cwd /path/to/project
```

Without `--message`, the last agent message in the transcript is checked.

## Limits

claim-check is a guardrail against honest mistakes and overclaiming by a cooperating agent, not a security control.

- Claim detection uses patterns, not a language model. It misses claims phrased in other ways ("everything is green now") and sometimes flags descriptive sentences. Only English and Korean are covered.
- Only test, build and lint/type-check claims are checked. "Fixed", "works" and "deployed" are not.
- Only Bash tool calls count as evidence. Checks run through MCP tools, `!` shell commands you type, CI, or outside Claude Code are not seen.
- A run is matched by kind, not by scope: a claim that *all* tests pass is backed by the last test run even if that run selected a subset. The report names the command so you can see this.
- When one command runs several checks and hides their exit codes, a summary line is assigned by position (first check, first line; last check, last line). With fewer summary lines than checks the outcome is unknown.
- Shell edits are recognized by pattern; a program that edits files in some other way is not seen.
- A transcript is the harness's record of what ran. An agent that wants to deceive can still print fake output; claim-check makes casual overclaiming visible, it does not prove the tests are good. For that, see [mutation-gate](https://github.com/godic97/mutation-gate).

## Development

```
python3 -m venv .venv && .venv/bin/pip install pytest mutmut
.venv/bin/python -m pytest -q
```

## License

MIT. See [LICENSE](LICENSE).
