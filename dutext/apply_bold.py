from __future__ import annotations

import re


class ApplyError(ValueError):
    pass


def _find_words(tex: str, words: list[str]) -> re.Match[str] | None:
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    return re.search(pattern, tex)


def longest_span(tex: str, words: list[str]) -> list[str]:
    """Longest consecutive extracted words that still occur in the TeX source."""
    n = len(words)
    for length in range(n, 0, -1):
        for start in range(0, n - length + 1):
            chunk = words[start : start + length]
            if _find_words(tex, chunk):
                return chunk
    raise ApplyError("could not find that text in the source")


def apply_bold(tex: str, phrase: str) -> tuple[str, str]:
    """Wrap the best matching span. Returns (new_tex, wrapped_phrase)."""
    words = [w for w in phrase.split() if w]
    if not words:
        raise ApplyError("no text inside the circle")
    chunk = longest_span(tex, words)
    match = _find_words(tex, chunk)
    if match is None:
        raise ApplyError("could not find that text in the source")
    inner = match.group(0)
    if re.search(r"\\textbf\{" + re.escape(inner) + r"\}", tex):
        return tex, inner
    wrapped = r"\textbf{" + inner + "}"
    return tex[: match.start()] + wrapped + tex[match.end() :], inner
