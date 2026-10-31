"""Posts and articles from a LinkedIn data export: the zip (or its unzipped folder) the
person downloads from LinkedIn's "Get a copy of your data" page and hands over (D29).

Never contacts LinkedIn. Only the files with their own published writing are opened:
`Shares.csv` (posts), the `Articles/` HTML files and, when asked, `Comments.csv`.
Everything else in the export (connections, messages, profile) is never read.

LinkedIn has renamed columns and moved files between export versions, so columns are
found by any of several names, files by name anywhere in the export, and a missing
file just means nothing of that kind.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from askthe.core.interfaces import ExportContents
from askthe.core.models import Creator, RawVideo, Transcript, TranscriptKind, VideoMeta

SOURCE = "linkedin-export"
POST, ARTICLE, COMMENT = "LinkedIn post", "LinkedIn article", "LinkedIn comment"
TITLE_CHARS = 80

# Column names seen in different export versions, normalised (lowercase, letters and
# digits only). The first non-empty one wins.
DATE_COLUMNS = ("date", "createdat", "created", "createddate", "publishedat", "sharedate")
LINK_COLUMNS = ("sharelink", "link", "postlink", "shareurl", "url", "permalink")
POST_TEXT_COLUMNS = ("sharecommentary", "commentary", "sharetext", "text", "content")
SHARED_COLUMNS = ("sharedurl", "sharedlink", "originalurl", "resharedurl", "repostedurl")
VISIBILITY_COLUMNS = ("visibility",)
COMMENT_TEXT_COLUMNS = ("message", "comment", "commenttext", "text", "content")

_URN = re.compile(r"urn:li:(share|activity|ugcpost):(\d+)", re.IGNORECASE)
_ACTIVITY_SLUG = re.compile(r"[-_](activity|share|ugcpost)-(\d{6,})", re.IGNORECASE)
_COMMENT_URN = re.compile(r"urn:li:comment:\((?:\w+):\d+,(\d+)\)", re.IGNORECASE)
_HASHTAG = re.compile(r"\{hashtag\|\\?#\|([^}]*)\}")  # LinkedIn's markup for "#word"
_DATED_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m/%d/%y, %I:%M %p",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
)


class LinkedInExportSource:
    """Implements ExportSource for LinkedIn's member data export."""

    def read_export(
        self, creator: Creator, path: Path, include_comments: bool = False
    ) -> ExportContents:
        files = _ExportFiles(Path(path))
        language = creator.languages[0] if creator.languages else "en"
        contents = ExportContents()
        now = datetime.now(UTC)

        def keep(meta: VideoMeta, text: str) -> None:
            if meta.platform_id in {i.meta.platform_id for i in contents.items}:
                contents.skipped[meta.platform_id] = "listed twice in the export"
                return
            contents.items.append(
                RawVideo(
                    creator_slug=creator.slug,
                    meta=meta,
                    transcript=Transcript(kind=TranscriptKind.MANUAL, language=language, text=text),
                    fetched_at=now,
                    source=SOURCE,
                )
            )

        for name in files.named("shares.csv"):
            for n, row in enumerate(_csv_rows(files.read_text(name)), start=1):
                result = post_from_row(row)
                if isinstance(result, str):
                    contents.skipped[f"{name} row {n}"] = result
                else:
                    keep(*result)
        for name in files.articles():
            result = article_from_html(files.read_text(name), PurePosixPath(name).stem)
            if isinstance(result, str):
                contents.skipped[name] = result
            else:
                keep(*result)
        if include_comments:
            for name in files.named("comments.csv"):
                for n, row in enumerate(_csv_rows(files.read_text(name)), start=1):
                    result = comment_from_row(row)
                    if isinstance(result, str):
                        contents.skipped[f"{name} row {n}"] = result
                    else:
                        keep(*result)
        return contents


# --- Reading the export ---------------------------------------------------------


class _ExportFiles:
    """The export's files by their path inside it, from a zip or an unzipped folder.
    Only listed until a file is asked for by name."""

    def __init__(self, path: Path) -> None:
        if path.is_dir():
            self._dir: Path | None = path
            self._zip: zipfile.ZipFile | None = None
            names = (p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file())
        elif path.is_file() and zipfile.is_zipfile(path):
            self._dir, self._zip = None, zipfile.ZipFile(path)
            names = (n for n in self._zip.namelist() if not n.endswith("/"))
        else:
            raise ValueError(f"{path} is not a LinkedIn export (a .zip file or a folder)")
        # macOS adds resource-fork copies ("__MACOSX/", "._Shares.csv") when zipping.
        self._names = sorted(
            n for n in names if "__MACOSX" not in n and not PurePosixPath(n).name.startswith("._")
        )

    def named(self, filename: str) -> list[str]:
        return [n for n in self._names if PurePosixPath(n).name.lower() == filename]

    def articles(self) -> list[str]:
        """HTML files in an `Articles` folder, at any depth."""
        return [
            n
            for n in self._names
            if PurePosixPath(n).suffix.lower() in (".html", ".htm")
            and any(part.lower() == "articles" for part in PurePosixPath(n).parts[:-1])
        ]

    def read_text(self, name: str) -> str:
        if self._zip is not None:
            data = self._zip.read(name)
        else:
            assert self._dir is not None
            data = (self._dir / name).read_bytes()
        return data.decode("utf-8-sig", errors="replace")


def _norm(column: str) -> str:
    return re.sub(r"[^a-z0-9]", "", column.lower())


def _csv_rows(text: str) -> list[dict[str, str]]:
    """Rows keyed by normalised column name. Some exports put notes above the header,
    so the header is the first row naming a date column."""
    rows = list(csv.reader(io.StringIO(text)))
    for i, row in enumerate(rows[:20]):
        header = [_norm(c) for c in row]
        if any(h in DATE_COLUMNS for h in header):
            return [
                dict(zip(header, (c.strip() for c in r), strict=False))
                for r in rows[i + 1 :]
                if any(c.strip() for c in r)
            ]
    return []


def _get(row: dict[str, str], columns: Sequence[str]) -> str:
    return next((row[c] for c in columns if row.get(c)), "")


def parse_date(text: str) -> datetime | None:
    """A date as LinkedIn writes it, in UTC when no zone is given."""
    text = re.sub(r"\s*(UTC|GMT)$", "", text.strip(), flags=re.IGNORECASE)
    if not text:
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def clean_text(text: str) -> str:
    """His text as written: LinkedIn's hashtag markup made plain, spacing tidied.
    Line breaks are kept; nothing else is changed."""
    text = _HASHTAG.sub(lambda m: f"#{m.group(1)}", text).replace("\r\n", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def title_from(text: str) -> str:
    """The first line, cut at a word to about TITLE_CHARS characters."""
    first = next((line for line in text.splitlines() if line.strip()), "").strip()
    if len(first) <= TITLE_CHARS:
        return first
    return first[:TITLE_CHARS].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:12]


def post_id_and_url(link: str) -> tuple[str | None, str | None]:
    """A stable ID from the post's URN, and a URL to cite, from the ShareLink column
    (a URL, URL-encoded or not, or a bare URN)."""
    decoded = unquote(unquote(link.strip()))
    url = link.strip() if decoded.lower().startswith("http") else None
    found = _URN.search(decoded)
    if found:
        kind, number = found.group(1).lower(), found.group(2)
        url = url or f"https://www.linkedin.com/feed/update/urn:li:{found.group(1)}:{number}/"
        return f"linkedin-{kind}-{number}", url
    found = _ACTIVITY_SLUG.search(urlparse(decoded).path)
    if found:
        return f"linkedin-{found.group(1).lower()}-{found.group(2)}", url
    return None, url


# --- Posts, articles and comments -------------------------------------------------


def post_from_row(row: dict[str, str]) -> tuple[VideoMeta, str] | str:
    """A post as (metadata, text), or why it's left out.

    A repost with no words of his own is skipped: it's someone else's post. A repost
    with his commentary keeps only the commentary; the export holds just a link to
    the reposted content, and it isn't his words anyway.
    """
    text = clean_text(_get(row, POST_TEXT_COLUMNS))
    if not text:
        if _get(row, SHARED_COLUMNS):
            return "repost with no commentary of his own"
        return "no text (an image or video with no words)"
    visibility = _get(row, VISIBILITY_COLUMNS).upper()
    if "CONNECTION" in visibility:
        return f"visible to connections only ({visibility})"
    published = parse_date(_get(row, DATE_COLUMNS))
    if published is None:
        return f"no readable date ({_get(row, DATE_COLUMNS)!r})"
    platform_id, url = post_id_and_url(_get(row, LINK_COLUMNS))
    if url is None:
        return "no link to the post, so it couldn't be cited"
    platform_id = platform_id or f"linkedin-post-{_short_hash(published.isoformat(), text)}"
    meta = VideoMeta(
        platform_id=platform_id,
        title=title_from(text),
        published_at=published,
        duration_s=0,
        medium=POST,
        url=url,
    )
    return meta, text


def comment_from_row(row: dict[str, str]) -> tuple[VideoMeta, str] | str:
    """A comment he wrote on someone's post, or why it's left out. Only his message is
    kept: the post it replies to is someone else's."""
    text = clean_text(_get(row, COMMENT_TEXT_COLUMNS))
    if not text:
        return "no text"
    published = parse_date(_get(row, DATE_COLUMNS))
    if published is None:
        return f"no readable date ({_get(row, DATE_COLUMNS)!r})"
    link = _get(row, LINK_COLUMNS)
    decoded = unquote(unquote(link))
    if not decoded.lower().startswith("http"):
        return "no link to the comment, so it couldn't be cited"
    found = _COMMENT_URN.search(decoded)
    suffix = found.group(1) if found else _short_hash(published.isoformat(), text)
    meta = VideoMeta(
        platform_id=f"linkedin-comment-{suffix}",
        title=f"Comment: {title_from(text)}",
        published_at=published,
        duration_s=0,
        medium=COMMENT,
        url=link,
    )
    return meta, text


def article_from_html(html: str, file_stem: str) -> tuple[VideoMeta, str] | str:
    """An article as (metadata, text), or why it's left out. Drafts (created, never
    published) are left out: they were never public."""
    page = _ArticlePage()
    page.feed(html)
    page.close()
    text = page.body
    if not text:
        return "no article text"
    published = parse_date(page.published)
    if published is None and page.created:
        return "a draft: created but never published"
    if published is None:  # no dates in the page at all: the file name's, if any
        dated = _DATED_NAME.match(file_stem)
        published = parse_date(dated.group(1)) if dated else None
    if published is None:
        return "no publish date"
    url = page.url()
    if url is None:
        return "no link to the article, so it couldn't be cited"
    slug = re.sub(r"[^a-z0-9]+", "-", PurePosixPath(urlparse(url).path).name.lower()).strip("-")
    meta = VideoMeta(
        platform_id=f"linkedin-article-{(slug or _short_hash(url))[:80]}",
        title=page.title_text() or title_from(text),
        published_at=published,
        duration_s=0,
        medium=ARTICLE,
        url=url,
    )
    return meta, text


_BLOCKS = {
    "p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "blockquote",
    "pre", "tr", "table", "section", "article", "figure", "figcaption", "hr",
}  # fmt: skip
_VOID = {"br", "hr", "img", "meta", "link", "input", "source", "wbr"}
_DATE_LINE = re.compile(r"^(created|published)(\s+on)?\s*:?\s*(.*)$", re.IGNORECASE)


class _ArticlePage(HTMLParser):
    """An exported article: its title, link, created and published dates, and text.

    LinkedIn's export writes the title as an <h1> (linking to the article), then
    "Created on ..." and "Published on ..." lines, then the article.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, str]] = []  # (tag, role)
        self._title: list[str] = []
        self._h1: list[str] = []
        self._body: list[str] = []
        self._links: list[tuple[str, bool]] = []  # (href, inside the h1)
        self.created = ""
        self.published = ""
        self.body = ""  # the article's text, set by close()

    def _roles(self) -> set[str]:
        return {role for _, role in self._stack}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self._links.append((values["href"] or "", "h1" in self._roles()))
        if tag in _BLOCKS:
            self._body.append("\n")
        if tag in _VOID:
            return
        classes = (values.get("class") or "").lower()
        role = ""
        if tag in ("head", "script", "style"):
            role = "skip"
        elif tag == "title":
            role = "title"
        elif tag == "h1" and not self._h1:
            role = "h1"
        elif "published" in classes:
            role = "published"
        elif "created" in classes:
            role = "created"
        self._stack.append((tag, role))

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCKS:
            self._body.append("\n")
        for i in range(len(self._stack) - 1, -1, -1):  # tolerate unclosed tags
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        roles = self._roles()
        if "title" in roles:
            self._title.append(data)
        elif "skip" in roles:
            return
        elif "h1" in roles:
            self._h1.append(data)
        elif "published" in roles:
            self.published += data
        elif "created" in roles:
            self.created += data
        else:
            self._body.append(data)

    def title_text(self) -> str:
        return " ".join("".join(self._h1 or self._title).split())

    def url(self) -> str | None:
        pulse = [h for h, _ in self._links if "linkedin.com/pulse/" in h]
        in_title = [h for h, in_h1 in self._links if in_h1 and h.startswith("http")]
        return next(iter(pulse + in_title), None)

    def close(self) -> None:
        super().close()
        lines = clean_text("".join(self._body)).split("\n")
        # Dates written as plain lines rather than marked by class: take them out.
        kept = []
        for line in lines:
            near_top = sum(1 for k in kept if k) < 3
            found = _DATE_LINE.match(line) if near_top else None
            if found and parse_date(found.group(3)):
                if found.group(1).lower() == "published":
                    self.published = self.published or found.group(3)
                else:
                    self.created = self.created or found.group(3)
                continue
            kept.append(line)
        self.created = _strip_label(self.created)
        self.published = _strip_label(self.published)
        self.body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _strip_label(text: str) -> str:
    found = _DATE_LINE.match(" ".join(text.split()))
    return found.group(3) if found else " ".join(text.split())
