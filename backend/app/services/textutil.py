import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    s = _Stripper()
    s.feed(html.unescape(value) if "&lt;" in value else value)
    text = "".join(s.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


_SUFFIX = re.compile(r"\b(inc|llc|ltd|gmbh|corp|corporation|co|ag|sa|plc|limited)\b\.?")


def norm_company(name: str) -> str:
    n = fold(name or "").lower()
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = _SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


_TITLE_NOISE = re.compile(r"\b(m/f/d|m/w/d|f/m/d|\(remote\)|remote|hybrid|urgent)\b")


def norm_title(title: str) -> str:
    t = fold(title or "").lower()
    t = _TITLE_NOISE.sub(" ", t)
    t = re.sub(r"[^a-z0-9+#. ]+", " ", t)
    t = re.sub(r"\bsr\b\.?", "senior", t)
    t = re.sub(r"\bjr\b\.?", "junior", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_location(loc: str | None) -> str:
    l = fold(loc or "").lower()
    l = re.sub(r"[^a-z0-9 ]+", " ", l)
    return re.sub(r"\s+", " ", l).strip()


def fingerprint(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", fold(text or "").lower()).strip()
    return hashlib.sha256(t.encode()).hexdigest()


def sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


_TRACKING = re.compile(r"^(utm_|gh_src|gh_jid|lever-|ref$|source$|src$|trk)", re.I)


def norm_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(sorted(q)), ""))


_WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")


def tokens(text: str) -> set[str]:
    return set(_WORD.findall(fold(text or "").lower()))


def contains_term(text: str, term: str) -> bool:
    """Whole-word / whole-phrase match, case-insensitive (so 'java' does not match 'javascript')."""
    t = fold(term or "").strip().lower()
    if not t:
        return False
    pat = r"(?<![a-z0-9+#])" + re.escape(t) + r"(?![a-z0-9+#])"
    return re.search(pat, fold(text or "").lower()) is not None


# ---- job description section extraction -------------------------------------------------
_HEADS = {
    "responsibilities": r"responsibilit|what you.?ll do|what you will do|the role|your role|day.to.day|duties",
    "required": r"requirement|qualification|what you.?ll bring|what we.?re looking for|must have|you have|about you|minimum",
    "preferred": r"nice to have|preferred|bonus|plus|desirable",
}


def split_sections(text: str) -> dict:
    out: dict[str, list[str]] = {"responsibilities": [], "required": [], "preferred": []}
    cur = None
    for raw in (text or "").splitlines():
        line = raw.strip().strip(":*#").strip()
        if not line:
            continue
        is_head = len(line) < 60 and not line.startswith("-")
        if is_head:
            low = line.lower()
            hit = next((k for k, p in _HEADS.items() if re.search(p, low)), None)
            if hit:
                cur = hit
                continue
            cur = None if cur and not re.search(r"[a-z]", low) else cur
            if low.endswith(":") or line.istitle():
                cur = None
                continue
        if cur:
            out[cur].append(line.lstrip("-•* ").strip())
    return out
