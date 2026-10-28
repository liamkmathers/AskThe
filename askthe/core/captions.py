"""Caption text handling: parsing caption files and cleaning caption noise.

Pure functions; reading the files is an adapter's job.
"""

from __future__ import annotations

import re

from askthe.core.models import CaptionFragment

_TIMESTAMP = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
_CUE_TIMING = re.compile(rf"{_TIMESTAMP}\s*-->\s*{_TIMESTAMP}")
_TAG = re.compile(r"<[^>]+>")


def _seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_cues(text: str) -> list[CaptionFragment]:
    """Parse WebVTT or SRT captions into fragments.

    Both formats are blocks separated by blank lines, each with a timing line
    (`00:01:02.500 --> 00:01:05.000`, with `,` instead of `.` in SRT) followed by
    text. Header blocks, cue numbers, NOTE blocks and inline tags are ignored.
    Consecutive cues repeating the same text (common in auto-captions) are merged.
    """
    fragments: list[CaptionFragment] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            match = _CUE_TIMING.search(line)
            if match:
                start = _seconds(*match.groups()[:4])
                end = _seconds(*match.groups()[4:])
                body = " ".join(_TAG.sub("", t).strip() for t in lines[i + 1 :])
                body = " ".join(body.split())
                if body:
                    if fragments and fragments[-1].text == body:
                        last = fragments[-1]
                        fragments[-1] = last.model_copy(
                            update={"duration_s": max(last.duration_s, end - last.start_s)}
                        )
                    else:
                        fragments.append(
                            CaptionFragment(
                                start_s=start, duration_s=max(end - start, 0), text=body
                            )
                        )
                break
    return fragments


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
