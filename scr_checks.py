import os
import re
from dataclasses import dataclass
from enum import StrEnum

from scr_diff import Status

PLAIN_TEXT_EXTENSIONS = ("md", "markdown", "txt")
LARGE_CHANGE_LINES = 1000


class Level(StrEnum):
    DANGER = "danger"
    WARN = "warn"
    NOTE = "note"


@dataclass
class Finding:
    level: Level
    message: str
    line: int = None
    key: str = ""
    path: str = ""
    view: str = ""
    file_key: str = ""


SECRET_PATTERNS = [
    ("private key", r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    ("AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("API key (sk-…)", r"\bsk-[A-Za-z0-9_-]{20,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("possible hard-coded credential",
     r"""(?i)\b(?:api[_-]?key|secret|passw(?:or)?d|token|auth)\w*["']?\s*[:=]\s*["'][^"'\s]{8,}["']"""),
]

LINE_RULES = (
    [(Level.DANGER, message, re.compile(pattern)) for message, pattern in SECRET_PATTERNS]
    + [(Level.WARN, "merge-conflict marker", re.compile(r"^(?:<{7}|>{7})(?:\s|$)")),
       (Level.WARN, "debug leftover",
        re.compile(r"\b(?:console\.(?:log|debug)\(|debugger\b|pdb\.set_trace\(|breakpoint\(\)"
                   r"|binding\.pry\b|var_dump\()")),
       (Level.NOTE, "TODO/FIXME", re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b"))]
)

PRINT_RE = re.compile(r"^\s*print\(")
TRAILING_SPACE_RE = re.compile(r"[ \t]+$")
SENSITIVE_FILE_RE = re.compile(r"(^|/)(\.env(\.(?!example|sample|template).*)?|id_(rsa|dsa|ecdsa|ed25519)"
                               r"|.*\.(pem|p12|pfx|jks|keystore)|credentials(\.json)?|\.npmrc|\.pypirc)$")

GENERATED_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
                   "Gemfile.lock", "composer.lock", "go.sum", "uv.lock"}
GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".lock")


def scan_line(text, ext):
    hits = [(level, message) for level, message, rule in LINE_RULES if rule.search(text)]
    if ext == "py" and PRINT_RE.search(text):
        hits.append((Level.NOTE, "print statement"))
    if ext not in PLAIN_TEXT_EXTENSIONS and TRAILING_SPACE_RE.search(text):
        hits.append((Level.NOTE, "trailing whitespace"))
    return hits


def scan_file(file_diff):
    if file_diff.status == Status.DELETED:
        return []

    hits = []
    if SENSITIVE_FILE_RE.search(file_diff.path):
        hits.append((Level.DANGER, "sensitive-looking file"))
    if file_diff.added > LARGE_CHANGE_LINES:
        hits.append((Level.WARN, f"large change (+{file_diff.added} lines)"))
    if file_diff.binary:
        hits.append((Level.NOTE, "binary file"))
    return hits


def is_generated(path):
    name = os.path.basename(path)
    return name in GENERATED_NAMES or name.endswith(GENERATED_SUFFIXES)
