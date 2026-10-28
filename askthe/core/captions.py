"""Transcript text handling: extracting text from caption files and cleaning caption noise.

Pure functions; reading the files is an adapter's job. Timing in caption files is
discarded: nothing in the system depends on it (docs/DECISIONS.md, D12).
"""

from __future__ import annotations

import re

_CUE_TIMING = re.compile(r"\d{1,2}:\d{2}[.,]\d{3}\s*-->")
_TAG = re.compile(r"<[^>]+>")


def caption_file_text(text: str) -> str:
    """The spoken text of a WebVTT or SRT file, in order.

    Both formats are blocks separated by blank lines: optional cue number, a timing
    line, then text. Header and NOTE blocks have no timing line and are skipped.
    Inline tags are removed, and a cue repeating the previous cue's text (common in
    auto-captions) is dropped.
    """
    lines_out: list[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            if _CUE_TIMING.search(line):
                body = " ".join(" ".join(_TAG.sub("", t).split()) for t in lines[i + 1 :])
                body = body.strip()
                if body and (not lines_out or lines_out[-1] != body):
                    lines_out.append(body)
                break
    return " ".join(lines_out)


_NOISE = re.compile(r"\[(?:music|applause|laughter|laughs|inaudible|silence)\]", re.IGNORECASE)
_SPEAKER_CHANGE = re.compile(r"(?:^|\s)>>(?=\s|$)")


def clean_caption_text(text: str) -> str:
    """Remove caption noise without changing the creator's words.

    Drops sound tags like [Music] and auto-caption speaker markers (>>), and
    normalises whitespace. Nothing else is altered, so quotes taken from cleaned
    text are still the creator's words.
    """
    text = _NOISE.sub(" ", text)
    text = _SPEAKER_CHANGE.sub(" ", text)
    return " ".join(text.split())
