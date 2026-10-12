import os
from dataclasses import dataclass
from enum import Enum
from itertools import zip_longest
from typing import NamedTuple

from scr_checks import Finding, Level, is_generated, scan_file, scan_line
from scr_diff import (ADDED_LINE, CONTEXT_LINE, META_LINE, REMOVED_LINE, Status,
                      changed_ranges)
from scr_highlight import extension_of, language_of, render_line
from scr_html import esc, fill

MAX_SOURCE_LINES = 3000
MAX_SOURCE_BYTES = 400_000
BINARY_SNIFF_BYTES = 8000
EXPAND_STEP = 20
MAX_WORD_DIFF_PAIRS = 50
MAX_LISTED_FINDINGS = 300

HUNK_CLASS = "hunk"
TAIL_CLASS = "hunk tail"
EMPTY_NUMBER_CELL = '<td class="ln"></td>'
EMPTY_SIDE = '<td class="ln empty"></td><td class="code empty"></td>'


class Layout(Enum):
    UNIFIED = "unified"
    SPLIT = "split"


class Expand(Enum):
    ALLOWED = "allowed"
    NONE = "none"


class ContextLine(NamedTuple):
    text: str


class MetaLine(NamedTuple):
    text: str


class ChangeBlock(NamedTuple):
    removed: list
    added: list


class Gap(NamedTuple):
    start: int
    end: int
    offset: int


@dataclass
class RenderedFile:
    html: str
    nav: str
    added: int
    removed: int
    findings: list
    source: tuple


@dataclass
class View:
    files: int
    added: int
    removed: int
    html: str
    nav: str
    findings: list
    sources: dict


def number_cell(number, key=None, css=""):
    classes = f"ln {css}".strip()
    if not key:
        return f'<td class="{classes}"></td>'
    return f'<td class="{classes}" data-key="{key}">{number}</td>'


def code_cell(sign, body, css="", tags=""):
    classes = f"code {css}".strip()
    return (f'<td class="{classes}"><span class="sign">{sign}</span>'
            f'<span class="cc">{body}</span>{tags}</td>')


def warning_tags(hits):
    return "".join(f'<span class="wtag {level}" title="{esc(message)}">⚠ {esc(message)}</span>'
                   for level, message in hits)


def expand_buttons(gap):
    hidden = gap.end - gap.start + 1
    if hidden <= EXPAND_STEP:
        return (f'<span class="exp-btns"><button class="exp-btn" data-mode="all" '
                f'title="Show {hidden} hidden lines">↕ {hidden}</button></span>')
    return ('<span class="exp-btns">'
            f'<button class="exp-btn" data-mode="top" title="Show {EXPAND_STEP} lines after the previous hunk">↓</button>'
            f'<button class="exp-btn" data-mode="bottom" title="Show {EXPAND_STEP} lines before the next hunk">↑</button>'
            f'<button class="exp-btn" data-mode="all" title="Show all {hidden} hidden lines">↕ {hidden}</button></span>')


def gap_row(gap_id, gap, label, layout, css_class=HUNK_CLASS):
    attrs, buttons = "", ""
    if gap:
        attrs = f' data-gid="{gap_id}" data-s="{gap.start}" data-e="{gap.end}" data-off="{gap.offset}"'
        buttons = expand_buttons(gap)
    text = f'<span class="hh">{esc(label)}</span>' if label else ""
    if layout is Layout.SPLIT:
        return f'<tr class="{css_class}"{attrs}><td class="ln"></td><td class="code" colspan="3">{buttons}{text}</td></tr>'
    return f'<tr class="{css_class}"{attrs}><td class="ln" colspan="2"></td><td class="code">{buttons}{text}</td></tr>'


def group_lines(lines):
    index = 0
    while index < len(lines):
        kind, text = lines[index]
        if kind == CONTEXT_LINE:
            yield ContextLine(text)
            index += 1
            continue
        if kind == META_LINE:
            yield MetaLine(text)
            index += 1
            continue

        removed, added = [], []
        while index < len(lines) and lines[index][0] == REMOVED_LINE:
            removed.append(lines[index][1])
            index += 1
        while index < len(lines) and lines[index][0] == ADDED_LINE:
            added.append(lines[index][1])
            index += 1
        yield ChangeBlock(removed, added)


def context_rows(old_no, new_no, text, lang):
    body, key = render_line(text, lang), f"n{new_no}"
    old_cell, new_cell = number_cell(old_no, key), number_cell(new_no, key)
    unified = f'<tr class="ctx" data-k="{key}">{old_cell}{new_cell}{code_cell(" ", body)}</tr>'
    split = f'<tr class="ctx" data-k="{key}">{old_cell}{code_cell(" ", body)}{new_cell}{code_cell(" ", body)}</tr>'
    return unified, split


def meta_rows(text):
    escaped = esc(text)
    unified = f'<tr class="meta"><td class="ln" colspan="2"></td><td class="code">{escaped}</td></tr>'
    split = f'<tr class="meta"><td class="ln"></td><td class="code" colspan="3">{escaped}</td></tr>'
    return unified, split


def word_marks(removed, added):
    removed_marks, added_marks = [[] for _ in removed], [[] for _ in added]
    pairs = min(len(removed), len(added), MAX_WORD_DIFF_PAIRS)
    for index in range(pairs):
        removed_marks[index], added_marks[index] = changed_ranges(removed[index], added[index])
    return removed_marks, added_marks


def record_findings(text, ext, line_no, findings):
    hits = scan_line(text, ext)
    for level, message in hits:
        findings.append(Finding(level, message, line=line_no, key=f"n{line_no}"))
    return warning_tags(hits)


def split_side(number, key_prefix, sign, body, css, tags=""):
    key = f"{key_prefix}{number}"
    return key, number_cell(number, key, css) + code_cell(sign, body, css, tags)


def change_rows(old_no, new_no, block, lang, ext, findings):
    removed_marks, added_marks = word_marks(block.removed, block.added)
    removed_html = [render_line(text, lang, marks) for text, marks in zip(block.removed, removed_marks)]
    added_html = [render_line(text, lang, marks) for text, marks in zip(block.added, added_marks)]
    added_tags = [record_findings(text, ext, new_no + index, findings)
                  for index, text in enumerate(block.added)]

    unified = []
    for index, body in enumerate(removed_html):
        key = f"o{old_no + index}"
        unified.append(f'<tr class="del" data-k="{key}">{number_cell(old_no + index, key)}'
                       f'{EMPTY_NUMBER_CELL}{code_cell("-", body)}</tr>')
    for index, body in enumerate(added_html):
        key = f"n{new_no + index}"
        unified.append(f'<tr class="add" data-k="{key}">{EMPTY_NUMBER_CELL}'
                       f'{number_cell(new_no + index, key)}{code_cell("+", body, tags=added_tags[index])}</tr>')

    removed_sides = [split_side(old_no + index, "o", "-", body, "del")
                     for index, body in enumerate(removed_html)]
    added_sides = [split_side(new_no + index, "n", "+", body, "add", added_tags[index])
                   for index, body in enumerate(added_html)]
    split = []
    for removed_side, added_side in zip_longest(removed_sides, added_sides,
                                                fillvalue=(None, EMPTY_SIDE)):
        keys = " ".join(key for key, _ in (removed_side, added_side) if key)
        split.append(f'<tr class="chg" data-k="{keys}">{removed_side[1]}{added_side[1]}</tr>')
    return "".join(unified), "".join(split)


def render_hunk(hunk, lang, ext, findings):
    unified, split = [], []
    old_no, new_no = hunk.first_old, hunk.first_new
    for block in group_lines(hunk.lines):
        match block:
            case ContextLine(text):
                rows = context_rows(old_no, new_no, text, lang)
                old_no, new_no = old_no + 1, new_no + 1
            case MetaLine(text):
                rows = meta_rows(text)
            case ChangeBlock(removed, added):
                rows = change_rows(old_no, new_no, block, lang, ext, findings)
                old_no, new_no = old_no + len(removed), new_no + len(added)
        unified.append(rows[0])
        split.append(rows[1])
    return "".join(unified), "".join(split)


def read_source(repo, path):
    full_path = os.path.join(repo, path)
    if os.path.islink(full_path) or not os.path.isfile(full_path):
        return None
    if os.path.getsize(full_path) > MAX_SOURCE_BYTES:
        return None

    with open(full_path, "rb") as handle:
        data = handle.read()
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return None

    lines = data.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines if len(lines) <= MAX_SOURCE_LINES else None


def load_source(repo, file_diff, expand):
    if expand is Expand.NONE:
        return None
    if file_diff.status == Status.DELETED or file_diff.binary:
        return None
    return read_source(repo, file_diff.path)


def render_hunks(file_diff, file_id, source_len, lang, ext, findings):
    unified, split = [], []
    next_new = next_old = 1
    for index, hunk in enumerate(file_diff.hunks):
        gap = None
        if source_len is not None and next_new <= hunk.first_new - 1:
            gap = Gap(next_new, hunk.first_new - 1, hunk.first_old - hunk.first_new)

        gap_id = f"{file_id}-{index}"
        hunk_unified, hunk_split = render_hunk(hunk, lang, ext, findings)
        unified += [gap_row(gap_id, gap, hunk.header, Layout.UNIFIED), hunk_unified]
        split += [gap_row(gap_id, gap, hunk.header, Layout.SPLIT), hunk_split]
        next_new, next_old = hunk.next_new, hunk.next_old

    if source_len is not None and next_new <= source_len:
        gap = Gap(next_new, source_len, next_old - next_new)
        unified.append(gap_row(f"{file_id}-tail", gap, "", Layout.UNIFIED, TAIL_CLASS))
        split.append(gap_row(f"{file_id}-tail", gap, "", Layout.SPLIT, TAIL_CLASS))

    return (f'<div class="tables"><table class="diff unified">{"".join(unified)}</table>'
            f'<table class="diff split"><colgroup><col class="cn"><col><col class="cn"><col></colgroup>'
            f'{"".join(split)}</table></div>')


def render_body(file_diff, file_id, source_len, lang, ext, findings):
    if file_diff.binary:
        return '<div class="nbody">Binary file not shown.</div>'
    if not file_diff.hunks:
        return '<div class="nbody">No textual changes (mode change or pure rename).</div>'
    return render_hunks(file_diff, file_id, source_len, lang, ext, findings)


def render_nav_link(file_id, file_key, path, file_diff):
    return (f'<a href="#{file_id}" class="navlink" data-fkey="{esc(file_key)}" data-status="{file_diff.status}">'
            f'<span class="vd">✓</span><span class="nn">{esc(path)}</span>'
            f'<span class="s"><b class="p">+{file_diff.added}</b> <b class="m">−{file_diff.removed}</b></span></a>')


def render_file(view, index, file_diff, repo, expand, template):
    path = file_diff.path
    ext, lang = extension_of(path), language_of(path)
    file_id, file_key = f"f-{view}-{index}", f"{view}::{path}"

    source_lines = load_source(repo, file_diff, expand)
    source_len = len(source_lines) if source_lines is not None else None
    source_html = [render_line(line, lang) for line in source_lines] if source_lines is not None else None

    line_findings = []
    body = render_body(file_diff, file_id, source_len, lang, ext, line_findings)

    file_hits = scan_file(file_diff)
    tags = warning_tags(file_hits)
    if is_generated(path):
        tags += '<span class="wtag note">generated · collapsed</span>'
    title = f'{esc(file_diff.old)} → {esc(file_diff.new)}' if file_diff.status == Status.RENAMED else esc(path)

    card = fill(template, id=file_id, fkey=esc(file_key), view=view, path=esc(path),
                status=str(file_diff.status), generated="1" if is_generated(path) else "0",
                title=title, tags=tags, adds=str(file_diff.added), dels=str(file_diff.removed),
                body=body)

    findings = line_findings + [Finding(level, message) for level, message in file_hits]
    for finding in findings:
        finding.path, finding.view, finding.file_key = path, view, file_key

    return RenderedFile(card, render_nav_link(file_id, file_key, path, file_diff),
                        file_diff.added, file_diff.removed, findings,
                        (file_key, source_html) if source_html is not None else None)


def build_view(view, files, repo, expand, template):
    rendered = [render_file(view, index, file_diff, repo, expand, template)
                for index, file_diff in enumerate(files)]
    return View(files=len(files),
                added=sum(item.added for item in rendered),
                removed=sum(item.removed for item in rendered),
                html="".join(item.html for item in rendered)
                     or '<div class="empty">No changes to review.</div>',
                nav="".join(item.nav for item in rendered),
                findings=[finding for item in rendered for finding in item.findings],
                sources=dict(item.source for item in rendered if item.source))


def finding_item(finding):
    where = esc(finding.path) + (f":{finding.line}" if finding.line else "")
    return (f'<li class="w-{finding.level}"><a href="#" data-goto="1" data-view="{esc(finding.view)}" '
            f'data-fkey="{esc(finding.file_key)}" data-key="{finding.key}">{where}</a> — {esc(finding.message)}</li>')


def warnings_html(findings):
    if not findings:
        return ""

    level_rank = {level: rank for rank, level in enumerate(Level)}
    ordered = sorted(findings, key=lambda item: (level_rank[item.level], item.path, item.line or 0))
    counts = {level: sum(1 for item in ordered if item.level == level) for level in Level}

    items = [finding_item(item) for item in ordered[:MAX_LISTED_FINDINGS]]
    if len(ordered) > MAX_LISTED_FINDINGS:
        items.append(f'<li class="more">… and {len(ordered) - MAX_LISTED_FINDINGS} more</li>')

    summary = " · ".join(f'<b class="c-{level}">{count} {level}</b>'
                         for level, count in counts.items() if count)
    open_attr = "open" if counts[Level.DANGER] or counts[Level.WARN] else ""
    return (f'<details class="warnings" {open_attr}>'
            f'<summary>⚠ Automatic checks: {summary}</summary><ul>{"".join(items)}</ul></details>')
