"""Text cleaning that keeps line structure. Original page text is retained separately."""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))
_BLANKS = re.compile(r"\n{3,}")
_SPACE_RUN = re.compile(r" {4,}")  # long runs add nothing; 3 spaces still mark a column gap


def clean_text(raw: str) -> str:
    """NFKC-normalise, unify newlines/whitespace, drop control chars. Never reorders content.

    Tabs become three spaces so column gaps stay detectable by the extractor.
    Evidence offsets are computed on this cleaned text.
    """
    text = unicodedata.normalize("NFKC", raw).translate(_ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    text = text.replace("\t", "   ").replace("\u00a0", " ")
    text = "".join(ch for ch in text if ch == "\n" or ch >= " ")
    lines = [_SPACE_RUN.sub("   ", ln.rstrip()) for ln in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip("\n")
