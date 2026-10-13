import difflib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import accumulate

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]")
FILE_HEADER_RE = re.compile(r"diff --git a/(.*) b/(.*)$")
NO_FILE = "/dev/null"
MIN_SIMILARITY = 0.4

ADDED_LINE = "+"
REMOVED_LINE = "-"
CONTEXT_LINE = " "
META_LINE = "\\"
LINE_KINDS = (ADDED_LINE, REMOVED_LINE, CONTEXT_LINE, META_LINE)


class Status(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass
class Hunk:
    header: str
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list = field(default_factory=list)

    @property
    def first_old(self):
        return self.old_start if self.old_len > 0 else self.old_start + 1

    @property
    def first_new(self):
        return self.new_start if self.new_len > 0 else self.new_start + 1

    @property
    def next_old(self):
        return self.old_start + self.old_len if self.old_len > 0 else self.old_start + 1

    @property
    def next_new(self):
        return self.new_start + self.new_len if self.new_len > 0 else self.new_start + 1


@dataclass
class FileDiff:
    old: str
    new: str
    status: Status = Status.MODIFIED
    binary: bool = False
    hunks: list = field(default_factory=list)

    @property
    def path(self):
        return self.old if self.status == Status.DELETED else self.new

    def count(self, kind):
        return sum(
            1 for hunk in self.hunks for line_kind, _ in hunk.lines if line_kind == kind
        )

    @property
    def added(self):
        return self.count(ADDED_LINE)

    @property
    def removed(self):
        return self.count(REMOVED_LINE)


def start_file(line):
    match = FILE_HEADER_RE.match(line)
    return FileDiff(
        old=match.group(1) if match else "", new=match.group(2) if match else ""
    )


def path_after(line, git_prefix):
    if line.startswith(git_prefix):
        return line[len(git_prefix) :]
    return line[4:]


def read_marker(side, line):
    if line[4:] == NO_FILE:
        return
    return path_after(line, "--- a/" if side == "old" else "+++ b/")


def apply_header(entry, line):
    if line.startswith("new file mode"):
        entry.status = Status.ADDED
    elif line.startswith("deleted file mode"):
        entry.status = Status.DELETED
    elif line.startswith("rename from "):
        entry.status, entry.old = Status.RENAMED, line[len("rename from ") :]
    elif line.startswith("rename to "):
        entry.new = line[len("rename to ") :]
    elif line.startswith("Binary files"):
        entry.binary = True
    elif line.startswith("--- "):
        entry.old = read_marker("old", line) or entry.old
    elif line.startswith("+++ "):
        entry.new = read_marker("new", line) or entry.new
    else:
        return False
    return True


def start_hunk(match, line):
    return Hunk(
        header=line,
        old_start=int(match.group(1)),
        old_len=int(match.group(2) or 1),
        new_start=int(match.group(3)),
        new_len=int(match.group(4) or 1),
    )


def parse_diff(text):
    files = []
    current = hunk = None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            current, hunk = start_file(line), None
            files.append(current)
            continue
        if current is None:
            continue
        if hunk is None and apply_header(current, line):
            continue

        match = HUNK_RE.match(line)
        if match:
            hunk = start_hunk(match, line)
            current.hunks.append(hunk)
        elif hunk is not None and line[:1] in LINE_KINDS:
            hunk.lines.append((line[0], line[1:]))
    return files


def changed_ranges(old_line, new_line):
    old_tokens, new_tokens = TOKEN_RE.findall(old_line), TOKEN_RE.findall(new_line)
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    if matcher.ratio() < MIN_SIMILARITY:
        return [], []

    old_offsets = [0, *accumulate(map(len, old_tokens))]
    new_offsets = [0, *accumulate(map(len, new_tokens))]
    old_ranges, new_ranges = [], []
    for op, old_from, old_to, new_from, new_to in matcher.get_opcodes():
        if op == "equal":
            continue
        if old_to > old_from:
            old_ranges.append((old_offsets[old_from], old_offsets[old_to]))
        if new_to > new_from:
            new_ranges.append((new_offsets[new_from], new_offsets[new_to]))
    return old_ranges, new_ranges
