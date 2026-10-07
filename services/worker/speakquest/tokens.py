"""Script and transcript token normalisation.

Both the script and every aligner's output pass through :func:`normalize_words`
so they meet in the same vocabulary: lowercase, no punctuation, numbers
spelled out (aligners cannot time digits, and Transcribe may emit either
"2026" or "twenty twenty six").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from speakquest.contracts import ScriptInfo, ScriptToken

_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen",
)  # fmt: skip
_TENS = ("_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((10**9, "billion"), (10**6, "million"), (1000, "thousand"))
_ORDINAL_IRREGULAR = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}
_CURRENCY = {"$": ("dollar", "dollars"), "£": ("pound", "pounds"), "€": ("euro", "euros")}

# A comma or full stop breaks a phrase only before whitespace, so "3.5" and
# "1,000" survive intact.
_PHRASE_BREAK = re.compile(r"[;:!?…—]+|[,.]+(?=\s|$)|\s+-\s+|\n+")
_TOKEN = re.compile(
    r"(?P<cur>[$£€])?(?P<num>\d[\d,]*(?:\.\d+)?)(?P<suf>st|nd|rd|th|%|s)?|[^\W\d_]+(?:['’][^\W\d_]+)*",
    re.UNICODE,
)


def _under_thousand(n: int) -> list[str]:
    words: list[str] = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        words += [_ONES[hundreds], "hundred"]
    if rest >= 20:
        tens, ones = divmod(rest, 10)
        words.append(_TENS[tens])
        if ones:
            words.append(_ONES[ones])
    elif rest or not words:
        words.append(_ONES[rest])
    return words


def cardinal(n: int) -> list[str]:
    """Spell out a non-negative integer: 1204 → one thousand two hundred four."""
    if n < 0:
        return ["minus", *cardinal(-n)]
    if n < 1000:
        return _under_thousand(n)
    words: list[str] = []
    for value, name in _SCALES:
        if n >= value:
            head, n = divmod(n, value)
            words += [*cardinal(head), name]
    if n:
        words += _under_thousand(n)
    return words


def year(n: int) -> list[str]:
    """1999 → nineteen ninety nine; 2026 → twenty twenty six; 2005 → two thousand five."""
    if 2000 <= n <= 2009:
        return cardinal(n)
    high, low = divmod(n, 100)
    if low == 0:
        return [*cardinal(high), "hundred"]
    if low < 10:
        return [*cardinal(high), "oh", *cardinal(low)]
    return [*cardinal(high), *cardinal(low)]


def ordinal(n: int) -> list[str]:
    words = cardinal(n)
    last = words[-1]
    if last in _ORDINAL_IRREGULAR:
        words[-1] = _ORDINAL_IRREGULAR[last]
    elif last.endswith("y"):
        words[-1] = last[:-1] + "ieth"
    else:
        words[-1] = last + "th"
    return words


def _number_words(cur: str | None, num: str, suffix: str | None) -> list[str]:
    plain = num.replace(",", "")
    if "." in plain:
        whole, frac = plain.split(".", 1)
        words = [*cardinal(int(whole)), "point", *(_ONES[int(d)] for d in frac)]
    else:
        value = int(plain)
        if suffix in {"st", "nd", "rd", "th"}:
            words = ordinal(value)
        elif suffix == "s" and len(plain) == 4:  # 1990s
            words = year(value)
            words[-1] = words[-1][:-1] + "ies" if words[-1].endswith("y") else words[-1] + "s"
        elif (
            cur is None
            and suffix is None
            and len(plain) == 4
            and "," not in num
            and (1100 <= value <= 2099)
        ):
            words = year(value)
        else:
            words = cardinal(value)
    if suffix == "%":
        words.append("percent")
    if cur:
        singular, plural = _CURRENCY[cur]
        words.append(singular if plain == "1" else plural)
    return words


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_word(raw: str) -> list[str]:
    """Normalise one surface word (may expand to several tokens, or none)."""
    out: list[str] = []
    for m in _TOKEN.finditer(_fold(raw).replace("-", " ")):
        if m.group("num"):
            out += _number_words(m.group("cur"), m.group("num"), m.group("suf"))
        else:
            out.append(re.sub(r"['’]", "", m.group(0)).lower())
    return out


def normalize_words(text: str) -> list[str]:
    return [tok for raw in text.split() for tok in normalize_word(raw)]


@dataclass(frozen=True)
class _Piece:
    display: str
    phrase: int


def tokenize_script(text: str) -> ScriptInfo:
    """Split a script into normalised tokens annotated with their phrase index.

    Phrases are delimited by punctuation and line breaks; they are the unit
    for pitch-contour (MONO) and phrase-final loudness (FADE) checks.
    """
    tokens: list[ScriptToken] = []
    phrase = 0
    pieces: list[_Piece] = []
    pos = 0
    for brk in _PHRASE_BREAK.finditer(text):
        chunk = text[pos : brk.start()]
        pieces += [_Piece(w, phrase) for w in chunk.split()]
        if chunk.strip():
            phrase += 1
        pos = brk.end()
    tail = text[pos:]
    pieces += [_Piece(w, phrase) for w in tail.split()]
    if tail.strip():
        phrase += 1

    for piece in pieces:
        for norm in normalize_word(piece.display):
            display = re.sub(r"^[^\w$£€]+|[^\w%]+$", "", piece.display) or piece.display
            tokens.append(
                ScriptToken(index=len(tokens), norm=norm, display=display, phrase=piece.phrase)
            )
    # Renumber phrases densely (a phrase that held only punctuation vanishes).
    remap: dict[int, int] = {}
    for tok in tokens:
        remap.setdefault(tok.phrase, len(remap))
        tok.phrase = remap[tok.phrase]
    return ScriptInfo(text=text, tokens=tokens, phrase_count=len(remap))


_VOWEL_GROUPS = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    """Deterministic English syllable estimate (vowel-group heuristic).

    Used only as a *ratio* against the same words in the reference, so
    systematic bias cancels out; it just has to be stable.
    """
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    count = len(_VOWEL_GROUPS.findall(w))
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    if w.endswith("ed") and len(w) > 3 and w[-3] not in "td" and count > 1:
        count -= 1
    return max(1, count)
