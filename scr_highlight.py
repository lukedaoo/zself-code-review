import os
import re
from itertools import groupby

from scr_html import esc

MAX_HIGHLIGHT_CHARS = 1000

STRING_PATTERN = r'"(?:\\.|[^"\\])*"?|\'(?:\\.|[^\'\\])*\'?|`(?:\\.|[^`\\])*`?'
NUMBER_PATTERN = r"\b\d[\w.]*"

KEYWORDS = {
    "py": "and as assert async await break class continue def del elif else except finally "
          "for from global if import in is lambda None nonlocal not or pass raise return try "
          "while with yield True False self",
    "clike": "abstract async await break case catch class const continue default defer do else "
             "enum export extends false final finally fn for func function go if impl implements "
             "import in instanceof interface let match mut namespace new null nil package private "
             "protected pub public return static struct super switch this throw true try type "
             "typeof use var void while yield int long char float double bool string byte",
    "hash": "if then else elif fi for while do done in case esac function return local export "
            "def end class module require true false nil",
    "sql": "select from where insert update delete into values join on group by "
           "order limit create table alter drop index and or not null as",
    "json": "true false null",
}

COMMENT_PATTERNS = {
    "py": r"#.*",
    "clike": r"//.*|/\*.*?(?:\*/|$)",
    "hash": r"#.*",
    "sql": r"--.*",
    "json": None,
    "css": r"/\*.*?(?:\*/|$)",
}

EXTENSIONS = {
    "py": "py pyi",
    "clike": "js jsx ts tsx mjs cjs java c h cpp cc hpp cs go rs kt swift php scala dart",
    "hash": "sh bash zsh yml yaml toml rb pl r mk dockerfile conf ini",
    "sql": "sql",
    "json": "json jsonc",
    "css": "css scss less",
}

LANGUAGE_BY_EXTENSION = {ext: lang for lang, exts in EXTENSIONS.items() for ext in exts.split()}


def build_tokenizer(comment, keywords):
    parts = [f"(?P<c>{comment})"] if comment else []
    parts += [f"(?P<s>{STRING_PATTERN})", f"(?P<n>{NUMBER_PATTERN})"]
    if keywords:
        parts.append(r"(?P<k>\b(?:%s)\b)" % "|".join(keywords.split()))
    return re.compile("|".join(parts))


TOKENIZERS = {lang: build_tokenizer(comment, KEYWORDS.get(lang))
              for lang, comment in COMMENT_PATTERNS.items()}


def extension_of(path):
    base = os.path.basename(path).lower()
    return base.rsplit(".", 1)[-1] if "." in base else base


def language_of(path):
    return LANGUAGE_BY_EXTENSION.get(extension_of(path))


def token_kinds(text, lang):
    kinds = [None] * len(text)
    tokenizer = TOKENIZERS.get(lang)
    if not tokenizer:
        return kinds
    for match in tokenizer.finditer(text):
        kinds[match.start():match.end()] = [match.lastgroup] * (match.end() - match.start())
    return kinds


def marked_flags(text, marks):
    flags = [False] * len(text)
    for start, end in marks:
        flags[start:end] = [True] * (end - start)
    return flags


def wrap_segment(text, kind, marked):
    segment = esc(text)
    if kind:
        segment = f'<span class="t-{kind}">{segment}</span>'
    if marked:
        segment = f"<mark>{segment}</mark>"
    return segment


def render_line(text, lang, marks=()):
    if not text:
        return ""
    if len(text) > MAX_HIGHLIGHT_CHARS:
        return esc(text)

    kinds = token_kinds(text, lang)
    flags = marked_flags(text, marks)
    segments, position = [], 0
    for (kind, marked), run in groupby(zip(kinds, flags)):
        length = len(list(run))
        segments.append(wrap_segment(text[position:position + length], kind, marked))
        position += length
    return "".join(segments)
