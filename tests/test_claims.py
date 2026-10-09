import pytest

from claim_check.claims import find


def kinds(text):
    return [c.kind for c in find(text)]


@pytest.mark.parametrize("text, expected", [
    ("All tests pass.", ["test"]),
    ("The test suite passes now.", ["test"]),
    ("Tests are passing.", ["test"]),
    ("I ran the tests and they pass.", ["test"]),
    ("pytest: 12 passed in 0.4s.", ["test"]),
    ("The change passes all 42 tests.", ["test"]),
    ("The build succeeds.", ["build"]),
    ("It compiles cleanly.", ["build"]),
    ("The project builds successfully.", ["build"]),
    ("The build is green.", ["build"]),
    ("mypy reports no errors.", ["lint"]),
    ("No lint errors remain, and no type errors either.", ["lint"]),
    ("The lint check passes.", ["lint"]),
    ("It type-checks cleanly.", ["lint"]),
    ("All tests pass, but the build fails.", ["test"]),
])
def test_english_claims(text, expected):
    assert kinds(text) == expected


@pytest.mark.parametrize("text", [
    "Tests do not pass yet.",
    "The tests still don't pass.",
    "If the tests pass, merge it.",
    "Run pytest to make sure the tests pass.",
    "Tests should pass now.",
    "Do the tests pass?",
    "3 passed, 1 failed.",
    "20 of 21 tests passed.",
    "All tests pass except one.",
    "All tests pass but two.",
    "```\n12 passed\n```",
    "> All tests pass",
    'The hook looks for phrases like "tests pass".',
    "We need the build to succeed.",
    "Once lint passes, push.",
    "",
])
def test_english_non_claims(text):
    assert kinds(text) == []


@pytest.mark.parametrize("text, expected", [
    ("테스트 모두 통과.", ["test"]),
    ("테스트 149개가 통과했습니다.", ["test"]),
    ("단위 테스트 통과 확인했습니다.", ["test"]),
    ("테스트를 통과시켰습니다.", ["test"]),
    ("빌드 성공.", ["build"]),
    ("컴파일 오류 없음.", ["build"]),
    ("빌드가 잘 됨.", ["build"]),
    ("타입 체크 통과.", ["lint"]),
    ("린트 깨끗함.", ["lint"]),
    ("테스트는 통과했지만 빌드는 확인 못 함.", ["test"]),
    ("단위 테스트와 lint 통과.", ["test", "lint"]),
])
def test_korean_claims(text, expected):
    assert kinds(text) == expected


@pytest.mark.parametrize("text", [
    "테스트가 통과하지 않았습니다.",
    "테스트 통과 여부 확인 필요.",
    "테스트 통과 예상.",
    "테스트가 통과하도록 고쳤습니다.",
    "테스트가 통과할 때까지 고침.",
    "테스트 21개 중 20개 통과.",
    "테스트 1개 실패, 나머지 통과.",
    "강한 테스트면 통과",
    "테스트 통과했나요?",
    "테스트 코드를 작성했고, 빌드 설정은 그대로임.",
    "빌드되면 알려줘.",
    "테스트 안 통과",
    '"테스트 통과" 같은 주장을 찾음.',
])
def test_korean_non_claims(text):
    assert kinds(text) == []


def test_one_claim_per_kind_in_fixed_order():
    found = find("Build succeeds. All tests pass. The tests pass again. 린트 통과.")
    assert [c.kind for c in found] == ["test", "build", "lint"]
    assert found[0].quote == "All tests pass."


def test_quote_is_the_sentence_shortened():
    long = "After the refactor of the parser and the new cache layer and the retry logic, all tests pass."
    quote = find(long)[0].quote
    assert len(quote) == 80
    assert quote.endswith("…")
    assert quote.startswith("After the refactor")


def test_quote_drops_markdown_and_bullets():
    found = find("- **All tests pass** (`pytest -q`).")
    assert found[0].quote == "All tests pass (pytest -q)."


def test_sentences_split_on_punctuation_and_newlines():
    assert kinds("Tests fail.\nBuild succeeds") == ["build"]
    assert kinds("test_m.py passes.") == []  # a file name, not "tests pass"


@pytest.mark.parametrize("text", [
    "  > All tests pass",  # indented quote
    "All tests pass Except one.",
    "3 passed, 1 FAILED.",
    "20 Of 21 tests passed.",
    "테스트 통과했나요？",
])
def test_more_non_claims(text):
    assert kinds(text) == []


def test_a_skipped_sentence_does_not_stop_the_search():
    assert kinds("Do tests pass? All tests pass.") == ["test"]


def test_quote_limit_boundary():
    exact = "All tests pass" + "." * 66
    assert len(exact) == 80 and find(exact)[0].quote == exact
    spaced = "All tests pass " + "x" * 63 + " yy"  # character 79 is a space
    assert find(spaced)[0].quote == "All tests pass " + "x" * 63 + "…"


@pytest.mark.parametrize("text", ["테스트 통과 안 했습니다.", "테스트 통과 안 됐습니다.", "테스트 통과 안 함.", "빌드 성공 안 했음."])
def test_korean_negation_after_the_verb(text):
    assert kinds(text) == []
