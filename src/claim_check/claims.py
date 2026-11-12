"""Find claims in the agent's final message (English and Korean): tests, a build or a lint/type check passed,
or a commit, push or tag was made."""

import re
from dataclasses import dataclass

KINDS = ("test", "build", "lint", "commit", "push", "tag")


@dataclass
class Claim:
    kind: str
    quote: str  # the sentence the claim was found in, shortened for the report
    targets: tuple = ()  # names in the sentence that may say what was checked: deid-guard, tests/test_a.py
    count: int = None  # the number of passing tests the sentence claims, if it says one


# English. A claim is a subject followed by a success verb within a few words.
EN_TEST_SUBJECT = r"(?:tests?|test suite|suite|specs?|test cases?|pytest|vitest|jest|unit tests?)"
EN_BUILD_SUBJECT = r"(?:build|builds|compilation|compile|compiles)"
EN_LINT_SUBJECT = (r"(?:lint(?:er|ing)?|eslint|ruff|flake8|pylint|mypy|pyright|tsc|clippy|biome|"
                   r"type[ -]?check(?:s|er|ing)?|typecheck(?:s|er|ing)?)")
GAP = r"(?:\s+[\w'’-]+){0,3}?"
EN_ACTOR = r"(?:^[-*•\s]*|\b(?:I|we)(?:'ve|\s+have)?\s+(?:just\s+|also\s+|now\s+|already\s+)?|(?:,|\band)\s+)"

EN_PATTERNS = [
    ("test", re.compile(rf"\b{EN_TEST_SUBJECT}\b{GAP}\s+(?:pass(?:es|ed|ing)?|succeed(?:s|ed)?|green)\b", re.I), True),
    ("test", re.compile(rf"\bpass(?:es|ed|ing)?\s+(?:all\s+)?(?:the\s+|of\s+the\s+)?(?:\d+\s+)?(?:existing\s+|new\s+)?{EN_TEST_SUBJECT}\b", re.I), True),
    ("test", re.compile(r"\b[1-9]\d*\s+(?:tests?\s+)?passed\b", re.I), True),
    ("build", re.compile(rf"\b{EN_BUILD_SUBJECT}\b{GAP}\s+(?:succeed(?:s|ed)?|pass(?:es|ed)?|(?:is|was)\s+(?:green|clean|successful))\b", re.I), True),
    ("build", re.compile(r"\b(?:builds|compiles|built|compiled)\s+(?:cleanly|successfully|fine|without\s+(?:any\s+)?(?:errors|warnings))\b", re.I), True),
    ("build", re.compile(r"\b(?:build|compilation)\s+(?:is\s+)?(?:green|clean|successful)\b", re.I), True),
    ("lint", re.compile(rf"\b{EN_LINT_SUBJECT}\b{GAP}\s+(?:pass(?:es|ed)?|succeed(?:s|ed)?|(?:is|are|comes back)\s+clean|is\s+happy|"
                        r"(?:reports?|reported|shows?|showed|finds?|found)\s+no)\b", re.I), True),
    ("lint", re.compile(r"\bno\s+(?:remaining\s+)?(?:lint|linting|type|typing|mypy|eslint|ruff|tsc|pyright|clippy)\s+(?:errors|issues|warnings|problems)\b", re.I), False),
    ("lint", re.compile(r"\b(?:type[ -]?checks|lints)\s+(?:cleanly|clean|fine)\b", re.I), True),
    # Actions are reported by the one who did them: "Pushed main.", "I committed it", "committed and pushed".
    ("commit", re.compile(rf"{EN_ACTOR}committed\b", re.I), False),
    ("push", re.compile(rf"{EN_ACTOR}pushed\b", re.I), False),
    ("tag", re.compile(rf"{EN_ACTOR}tagged\b", re.I), False),
]
# Before the claim: words that turn it into a negation, a condition, an instruction, a plan or a hope.
EN_HEDGE = re.compile(
    r"\b(?:not|no|never|none|nothing|without|unless|if|whether|until|once|should|would|could|might|may|will|"
    r"can|cannot|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|haven't|hasn't|make|makes|"
    r"ensure|verify|check|confirm|run|rerun|re-run|please|expect|expected|hope|need|needs|want|try|before|"
    r"fail(?:s|ed|ing)?\s+to|so\s+that)\b",
    re.I)
# Inside the claim (between subject and verb): negations and modals only, since "lint check passes" is a claim.
EN_INSIDE = re.compile(
    r"\b(?:not|never|no\s+longer|should|would|could|might|may|will|can|cannot|need|needs|"
    r"can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|fail(?:s|ed)?\s+to|still)\b", re.I)
EN_CLAUSE_BREAK = re.compile(r",|;|:|\s—\s|\s-\s|\b(?:and|but|while|although|though|so)\b", re.I)

# Korean. The success verb follows the subject; negation and conditions come after the verb.
KO_GAP = r"(?:(?!실패|안\s|못\s|않|고[\s,]|며\s|면\s|지만|는데|,)[^.!?\n]){0,12}?"
# Actions: a longer gap, since tag names and hashes sit between the noun and the verb ("태그 x--v0.2.0도 올렸어").
ACT_GAP = r"(?:(?!실패|안\s|못\s|않|지만|는데)[^!?\n]){0,40}?"
KO_DONE = r"(?:했|하였|함|완료|됨|됐|되었|성공)"
# (kind, pattern, whether hedges inside the match count too)
KO_PATTERNS = [
    ("test", re.compile(rf"(?:테스트|pytest|vitest|jest|단위\s?테스트|유닛\s?테스트){KO_GAP}(?:통과|성공|패스|pass)", re.I), False),
    ("build", re.compile(rf"(?:빌드|컴파일){KO_GAP}(?:성공|통과|정상|완료|됩니다|됐|되었|잘\s?됨|에러\s?없|오류\s?없|문제\s?없)"), False),
    ("lint", re.compile(rf"(?:린트|린터|lint|eslint|ruff|mypy|pyright|tsc|clippy|타입\s?체크|타입\s?검사|정적\s?분석){KO_GAP}"
                        r"(?:통과|성공|깨끗|클린|에러\s?없|오류\s?없|문제\s?없|경고\s?없)", re.I), False),
    ("commit", re.compile(rf"커밋{ACT_GAP}(?:{KO_DONE}|해\s?뒀|해\s?놨)"), True),
    ("push", re.compile(rf"(?:push|푸시|푸쉬){ACT_GAP}{KO_DONE}|(?:깃허브|github|원격|origin)(?:에|으로|로)?\s*(?:올렸|올림|업로드\s?{KO_DONE})", re.I), True),
    ("tag", re.compile(rf"태그{ACT_GAP}(?:달았|달음|붙였|만들었|생성\s?{KO_DONE}|추가\s?{KO_DONE}|push\s?{KO_DONE}|올렸)", re.I), True),
]
KO_HEDGE = re.compile(
    r"않|못|안\s*(?:됨|돼|되|됐|함|했|해)|실패|여부|는지|는가|할지|될지|하면|되면|시키면|해야|돼야|되어야|도록|때까지|"
    r"할\s?수|될\s?수|할\s?것|될\s?것|예정|예상|추정|아마|것\s?같|필요|하길|되길|기를|해\s?보|확인해\s?주|려고|려면|겠")
KO_CLAUSE_END = re.compile(r",|;|지만|는데|으나|고[\s,]|며\s|면서|\s—\s")

FENCE = re.compile(r"```.*?(?:```|$)", re.S)
QUOTED = re.compile(r"\"[^\"\n]{1,60}\"|“[^”\n]{1,60}”|「[^」\n]{1,60}」")  # quoted phrases are examples, not claims
SENTENCE = re.compile(r"(?<=[.!?。])\s+|\n+")
# A target names something specific: a path, a file, a hyphenated or dotted name. Plain words are too vague.
TARGET = re.compile(r"[A-Za-z0-9_./~-]*[A-Za-z][A-Za-z0-9_./~-]*")
COUNT = re.compile(r"(?:테스트|tests?)\s*(\d+)\s*개|(\d+)\s*개\s*(?:의\s*)?(?:테스트|(?:모두|전부|다)?\s*통과)|"
                   r"(?<![\d.])(\d+)\s+(?:\w+\s+)?(?:tests?|passed|passing|pass)\b", re.I)


def _clean(text):
    text = FENCE.sub("\n", text)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]  # quoted text is not a claim
    return QUOTED.sub(" ", "\n".join(lines)).replace("`", "").replace("**", "")


def _shorten(sentence, limit=80):
    sentence = " ".join(sentence.split()).lstrip("-*• ")
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip() + "…"


def _en_claim(sentence, m, hedge_inside):
    start = 0
    for brk in EN_CLAUSE_BREAK.finditer(sentence, 0, m.start()):
        start = brk.end()
    if EN_HEDGE.search(sentence[start:m.start()]) or (hedge_inside and EN_INSIDE.search(m.group())):
        return False
    return not re.match(r"\s*,?\s*(?:except|apart from|other than|but\s+(?:one|two|three|a few|\d+))\b", sentence[m.end():], re.I)


def _ko_claim(sentence, m, hedge_inside):
    if hedge_inside and KO_HEDGE.search(m.group()):
        return False
    tail = sentence[m.end():]
    end = KO_CLAUSE_END.search(tail)
    tail = tail[:end.start()] if end else tail
    return not KO_HEDGE.search(tail[:20])


def _mixed_result(sentence):
    """'3 passed, 1 failed' or '20 of 21 passed' reports a failure, not a success."""
    if re.search(r"\b[1-9]\d*\s+(?:failed|failing|errors?)\b|[1-9]\d*\s*개?\s*실패", sentence, re.I):
        return True
    for total, passed in re.findall(r"(\d+)\s*개\s*중\s*(\d+)\s*개", sentence):
        if total != passed:
            return True
    for passed, total in re.findall(r"\b(\d+)\s*(?:/|of|out of)\s*(\d+)\b", sentence, re.I):
        if total != passed:
            return True
    return False


def _targets(sentence):
    names = (t.strip(".,:;~") for t in TARGET.findall(sentence))
    return tuple(dict.fromkeys(t for t in names if len(t) > 2 and not t.startswith("-") and set(t) & set("-_./")))


def _count(sentence):
    m = COUNT.search(sentence)
    return int(next(g for g in m.groups() if g)) if m else None


def find(message):
    """Every claim in the message: one per kind per sentence, in message order."""
    found = []
    for sentence in SENTENCE.split(_clean(message or "")):
        sentence = sentence.strip()
        if not sentence or sentence.endswith(("?", "？")) or _mixed_result(sentence):
            continue
        kinds = {kind for kind, pattern, hedge_inside in EN_PATTERNS
                 if any(_en_claim(sentence, m, hedge_inside) for m in pattern.finditer(sentence))}
        kinds |= {kind for kind, pattern, hedge_inside in KO_PATTERNS
                  if any(_ko_claim(sentence, m, hedge_inside) for m in pattern.finditer(sentence))}
        for kind in (k for k in KINDS if k in kinds):
            found.append(Claim(kind, _shorten(sentence), _targets(sentence), _count(sentence)))
    return found
