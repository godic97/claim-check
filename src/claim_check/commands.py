"""Classify shell commands as test, build or lint runs, and read their outcome from the output."""

import os
import re
import shlex
from dataclasses import dataclass, field

# Wrappers that run the real command after them: (words to drop, how many arguments they take).
WRAPPERS = {
    "time": 0, "nice": 0, "nohup": 0, "command": 0, "exec": 0, "caffeinate": 0,
    "timeout": 1, "gtimeout": 1,
    "npx": 0, "bunx": 0, "pnpx": 0, "uvx": 0,
}
# Wrapper options that take a value: `timeout -s KILL 60 pytest`, `nice -n 10 pytest`.
WRAPPER_VALUE_OPTIONS = {"timeout": {"-s", "--signal", "-k", "--kill-after"}, "gtimeout": {"-s", "--signal", "-k", "--kill-after"},
                         "nice": {"-n", "--adjustment"}}
RUNNERS = {  # tool + subcommand that runs whatever follows
    ("uv", "run"), ("poetry", "run"), ("pipenv", "run"), ("pdm", "run"), ("hatch", "run"), ("rye", "run"),
    ("pnpm", "exec"), ("pnpm", "dlx"), ("yarn", "dlx"), ("npm", "exec"), ("bundle", "exec"), ("pipx", "run"),
}
PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1")
SEPARATORS = {"||": "||", "&&": "&&", "|": "|", ";": ";", "\n": ";", "&": "&"}  # checked in this order
WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&"}
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}", "done", "fi"}
VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


@dataclass
class Segment:
    words: list  # normalized: the real tool first, variables set earlier in the command expanded
    op_after: str  # operator that follows this segment ("&&", "||", "|", ";", "&"), "" for the last one
    writes: list = field(default_factory=list)  # files this segment redirects output into


def split_heredocs(command):
    """(command without heredoc bodies, list of the bodies)."""
    bodies = []
    out = []
    lines = command.split("\n")
    i = 0
    while i < len(lines):
        out.append(lines[i])
        delimiters = [m.group(2) for m in HEREDOC.finditer(lines[i])]
        i += 1
        for delimiter in delimiters:
            body = []
            while i < len(lines) and lines[i].strip() != delimiter:
                body.append(lines[i])
                i += 1
            i += 1  # the delimiter line
            bodies.append("\n".join(body))
    return "\n".join(out), bodies


def _tokens(command):
    lex = shlex.shlex(command.replace("\\\n", " "), posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:  # unbalanced quotes: fall back to whitespace
        return [t for t in re.split(r"[ \t]+|(\n|&&|\|\||[;|])", command) if t]


def _operator(token):
    """The separator a punctuation token stands for, 'redirect' for a redirection, None for a word."""
    if not token or not set(token) <= set("();<>|&\n"):
        return None
    if token[0] in "<>" or token.startswith("&>"):
        return "redirect"
    for key, op in SEPARATORS.items():
        if key in token:
            return op
    return "group"  # ( and )


def segments(command):
    """Split a shell command into simple commands on && || ; | & and newlines, outside quotes and heredocs."""
    command, _ = split_heredocs(command)
    variables = {}
    out = []
    words, writes = [], []
    redirect = None  # the redirection token waiting for its target

    def expand(word):
        word = VARIABLE.sub(lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), word)
        return os.path.expanduser(word) if word.startswith("~") else word

    def close(op):
        nonlocal words, writes
        while words and words[0] in KEYWORDS:
            words = words[1:]
        if words and all(ENV_ASSIGN.match(w) for w in words):
            for w in words:  # `S=/tmp/x;` sets a variable for the rest of the command
                name, value = w.split("=", 1)
                variables[name] = expand(value)
            words = []
        if words or writes:
            out.append(Segment(normalize([expand(w) for w in words]), op, writes))
        elif out and out[-1].op_after == "&&":
            out[-1].op_after = op  # `pytest && X=1; echo`: the ; still hides pytest's status
        words, writes = [], []

    for token in _tokens(command):
        op = _operator(token)
        if op is None:
            if redirect is None:
                words.append(token)
            else:
                # `2>&1` arrives as `2` `>&` `1`: a descriptor, not a file.
                if redirect in WRITE_REDIRECTS and not (redirect == ">&" and token.isdigit()):
                    writes.append(expand(token))
                redirect = None
        elif op == "redirect":
            if words and words[-1].isdigit():
                words.pop()  # the file descriptor of `2>&1` or `2> err.log`
            redirect = token
        elif op != "group":
            close(op)
    close("")
    if out and out[-1].op_after == ";":
        out[-1].op_after = ""  # a trailing newline or ; does not hide the exit status
    return out


def _base(word):
    return os.path.basename(word)


def normalize(words):
    """Drop env assignments, wrappers and runners so the first word is the real tool."""
    words = list(words)
    while words:
        head = _base(words[0])
        if ENV_ASSIGN.match(words[0]) or head == "env":
            words = words[1:]
        elif head in WRAPPERS:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in WRAPPER_VALUE_OPTIONS.get(head, ()) else words[1:]
            words = words[WRAPPERS[head]:]
        elif len(words) > 1 and (head, words[1]) in RUNNERS:
            words = words[2:]
        elif re.fullmatch(r"python[0-9.]*", head) and len(words) > 2 and words[1] == "-m":
            words = words[2:]
        else:
            break
    if words:
        words[0] = _base(words[0])
    return words


def _script(words):
    """The package.json script a package-manager command runs, or None."""
    if len(words) < 2:
        return None
    if words[1] == "run" and len(words) > 2:
        return words[2]
    if words[0] in ("pnpm", "yarn", "bun") and not words[1].startswith("-"):
        return words[1]
    if words[1] in ("test", "t"):
        return "test"
    return None


def _script_kind(name):
    if re.match(r"(test|spec|e2e)", name):
        return "test"
    if re.match(r"(lint|typecheck|type-check|check-types|tsc|types)", name):
        return "lint"
    if re.match(r"(build|compile)", name):
        return "build"
    return None


TEST_TOOLS = {"pytest", "py.test", "tox", "nox", "vitest", "jest", "mocha", "ava", "rspec", "phpunit", "ctest", "unittest", "nextest"}
LINT_TOOLS = {"eslint", "ruff", "flake8", "pyflakes", "pycodestyle", "pylint", "mypy", "pyright", "basedpyright",
              "golangci-lint", "biome", "stylelint", "shellcheck"}
# build = `python -m build`; py_compile and compileall check that Python sources compile.
BUILD_TOOLS = {"cmake", "ninja", "xcodebuild", "webpack", "rollup", "esbuild", "build", "py_compile", "compileall"}
TEST_FILE = re.compile(r"(?:^|/)(?:tests?/.*\.\w+|test_[^/]*\.py|[^/]*_test\.(?:py|go)|[^/]*\.(?:test|spec)\.[cm]?[jt]sx?)$")


# Flags that print information instead of running the checks.
INFO_FLAGS = {"--version", "-V", "--help", "-h", "--collect-only", "--co", "--no-run", "--fixtures", "--list",
              "--listTests", "--showConfig", "--dry-run"}


def classify(words):
    """'test', 'build', 'lint' or None for one normalized command."""
    if not words or INFO_FLAGS & set(words[1:]):
        return None
    head, args = words[0], words[1:]
    if head in PACKAGE_MANAGERS:
        if head != "npm" and args and args[0] in TEST_TOOLS | LINT_TOOLS | BUILD_TOOLS | {"tsc", "vite", "next"}:
            return classify(args)  # `pnpm vitest`, `yarn tsc --noEmit`: a binary, not a script
        script = _script(words)
        return _script_kind(script) if script else None
    if head in TEST_TOOLS:
        return "test"
    if re.fullmatch(r"python[0-9.]*|node|tsx|ts-node", head):
        script = next((a for a in args if not a.startswith("-")), "")
        return "test" if TEST_FILE.search(script) or (head == "node" and "--test" in args) else None
    if head == "vite" or head == "next":
        return "build" if "build" in args else None
    if head == "tsc":
        return "lint" if "--noEmit" in args else "build"
    if head in LINT_TOOLS:
        return "lint"
    if head in BUILD_TOOLS:
        return "build" if head != "cmake" or "--build" in args else None
    sub = args[0] if args else ""
    if head == "claude" and args[:2] == ["plugin", "test"]:
        return "test"
    if head == "go":
        return {"test": "test", "build": "build", "vet": "lint"}.get(sub)
    if head == "cargo":
        return {"test": "test", "nextest": "test", "build": "build", "clippy": "lint", "check": "lint"}.get(sub)
    if head in ("deno", "swift", "mix", "dotnet"):
        return {"test": "test", "build": "build", "lint": "lint", "check": "lint"}.get(sub)
    if head in ("mvn", "mvnw"):
        goals = set(args)
        if goals & {"test", "verify", "install"}:
            return "test"
        return "build" if goals & {"compile", "package", "test-compile"} else None
    if head in ("gradle", "gradlew"):
        if any(a.startswith(("test", ":test")) or a.endswith(":test") or a == "check" for a in args):
            return "test"
        return "build" if any(a in ("build", "assemble") or "compile" in a.lower() for a in args) else None
    if head == "sbt":
        return "test" if any(a.startswith("test") for a in args) else ("build" if "compile" in args else None)
    if head == "make":
        if {"-n", "--just-print", "--recon", "-q", "--question"} & set(args):
            return None  # prints or checks, runs nothing
        targets = [a for a in args if not a.startswith("-") and "=" not in a]
        if any(t in ("test", "tests", "check") for t in targets):
            return "test"
        if any(t in ("lint", "typecheck") for t in targets):
            return "lint"
        return "build" if not targets or any(t in ("build", "all") for t in targets) else None
    return None


# Output markers. Fail markers win over pass markers.
FAIL_MARKERS = [
    re.compile(r"\b[1-9]\d*\s+(?:failed|failing|errors?)\b", re.I),
    re.compile(r"^FAIL(?:ED)?\b", re.M),
    re.compile(r"--- FAIL:"),
    re.compile(r"test result: FAILED"),
    re.compile(r"BUILD FAILURE|BUILD FAILED|Build FAILED"),
    re.compile(r"\berror TS\d+:"),
    re.compile(r"^error(?:\[E\d+\])?:", re.M),
    re.compile(r"Failed!\s+-\s+Failed:"),
    re.compile(r"npm ERR!|ELIFECYCLE|Command failed with exit code"),
    re.compile(r"command not found|No module named \w+"),  # the check never ran
]
EMPTY_MARKERS = [
    re.compile(r"collected 0 items|no tests ran|No test files found|No tests found|Ran 0 tests|no tests to run|0 passing", re.I),
]
PASS_MARKERS = [
    re.compile(r"\b[1-9]\d*\s+(?:passed|passing)\b"),
    re.compile(r"^ok\s+\S+", re.M),
    re.compile(r"test result: ok\."),
    re.compile(r"BUILD SUCCESS(?:FUL)?|Build succeeded"),
    re.compile(r"Passed!\s+-"),
    re.compile(r"All checks passed!|Success: no issues found|\b0 errors?\b"),
    re.compile(r"^OK\b", re.M),
    re.compile(r"Compiled successfully|✓ built in"),
]


def _line_at(output, pos):
    start = output.rfind("\n", 0, pos) + 1
    end = output.find("\n", pos)
    return output[start:end if end >= 0 else None]


def _first(markers, output):
    for marker in markers:
        m = marker.search(output)
        if m:
            return _line_at(output, m.start()).strip(" =-\t")[:100]
    return None


def _verdict(text):
    """('fail'|'empty'|'pass'|None, summary line) from output markers. Fail markers win."""
    for kind, markers in (("fail", FAIL_MARKERS), ("empty", EMPTY_MARKERS), ("pass", PASS_MARKERS)):
        line = _first(markers, text)
        if line:
            return kind, line
    return None, None


def _summary_lines(output):
    """Output lines that carry any marker, in order."""
    return [line for line in output.splitlines()
            if any(m.search(line) for m in FAIL_MARKERS + EMPTY_MARKERS + PASS_MARKERS)]


def masked(segs, i):
    """True when the command's exit status does not reflect segment i (a pipe, || or ; follows it)."""
    return any(seg.op_after not in ("&&", "") for seg in segs[i:])


def outcome(segs, i, exit_code, output):
    """('pass'|'fail'|'empty'|'unknown', summary) for segment i of a command that exited with exit_code.

    An exit code that belongs to the check decides; output markers decide only when it is hidden.
    """
    checks = [j for j, seg in enumerate(segs) if classify(seg.words)]
    later_checks = any(j > i for j in checks)
    if not masked(segs, i) and (exit_code == 0 or not later_checks):
        empty = _first(EMPTY_MARKERS, output) if len(checks) == 1 else None
        if empty:
            return "empty", empty
        if exit_code == 0:
            return "pass", _first(PASS_MARKERS, output) if len(checks) == 1 else None
        return "fail", (_first(FAIL_MARKERS, output) if len(checks) == 1 else None) or f"exit code {exit_code}"
    if len(checks) == 1:
        kind, summary = _verdict(output)
    else:
        # Several checks share the output. Their summary lines come in order: the first check gets the
        # first summary line, the last check the last one.
        lines = _summary_lines(output)
        pick = ""
        if len(lines) >= len(checks):  # fewer summary lines than checks: no way to tell whose they are
            pick = lines[0] if i == checks[0] else lines[-1] if i == checks[-1] else ""
        kind, summary = _verdict(pick)
    if kind:
        return kind, summary
    if masked(segs, i):
        return "unknown", "its exit status went through a pipe, `||` or `;`, and the output has no summary line"
    return "unknown", f"exit code {exit_code} could come from a later command in the same line"
