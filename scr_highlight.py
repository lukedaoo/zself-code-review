import os
import re
from dataclasses import dataclass
from itertools import groupby

from scr_html import esc

MAX_HIGHLIGHT_CHARS = 1000

QUOTED_PATTERN = r'"(?:\\.|[^"\\])*"?|\'(?:\\.|[^\'\\])*\'?'
STRING_PATTERN = QUOTED_PATTERN + r"|`(?:\\.|[^`\\])*`?"
TRIPLE_QUOTED_PATTERN = r'"""(?:\\.|[^\\])*?(?:"""|$)|\'\'\'(?:\\.|[^\\])*?(?:\'\'\'|$)'
TERMINATED_PATTERN = r'"[^"\n]*"|\'[^\'\n]*\''
DOUBLE_QUOTED_PATTERN = r'"(?:\\.|[^"\\])*"'
NUMBER_PATTERN = r"\b\d[\w.]*"
SLASH_COMMENT = r"//.*"
BLOCK_COMMENT = r"/\*.*?(?:\*/|$)"
C_COMMENT = SLASH_COMMENT + "|" + BLOCK_COMMENT
HASH_COMMENT = r"#.*"
GENERIC_COMMENT = HASH_COMMENT + "|" + C_COMMENT

C_KEYWORDS = (
    "auto break case char const continue default do double else enum extern float for goto if "
    "inline int long register restrict return short signed sizeof static struct switch typedef "
    "union unsigned void volatile while bool true false NULL size_t ssize_t "
    "int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t"
)

CPP_KEYWORDS = C_KEYWORDS + (
    " alignas alignof and asm catch class concept consteval constexpr constinit co_await "
    "co_return co_yield decltype delete dynamic_cast explicit export final friend mutable "
    "namespace new noexcept not nullptr operator or override private protected public "
    "reinterpret_cast requires static_assert static_cast template this thread_local throw try "
    "typeid typename using virtual string vector"
)

GO_KEYWORDS = (
    "break case chan const continue default defer else fallthrough for func go goto if import "
    "interface map package range return select struct switch type var true false nil iota "
    "string bool byte rune error any int int8 int16 int32 int64 uint uint8 uint16 uint32 uint64 "
    "uintptr float32 float64 complex64 complex128 append cap close copy delete len make new "
    "panic print println recover"
)

ZIG_KEYWORDS = (
    "addrspace align allowzero and anyframe anytype asm async await break callconv catch "
    "comptime const continue defer else enum errdefer error export extern fn for if inline "
    "linksection noalias noinline nosuspend opaque or orelse packed pub resume return struct "
    "suspend switch test threadlocal try union unreachable usingnamespace var volatile while "
    "true false null undefined void bool type anyerror noreturn "
    "u8 u16 u32 u64 u128 usize i8 i16 i32 i64 i128 isize f16 f32 f64 f128 c_int c_uint c_long"
)

PYTHON_KEYWORDS = (
    "and as assert async await break class continue def del elif else except finally "
    "for from global if import in is lambda None nonlocal not or pass raise return try "
    "while with yield True False self cls"
)

CLIKE_KEYWORDS = (
    "abstract async await break case catch class const continue default defer do else "
    "enum export extends false final finally fn for func function go if impl implements "
    "import in instanceof interface let match mut namespace new null nil package private "
    "protected pub public return static struct super switch this throw true try type "
    "typeof use var void while yield int long char float double bool string byte"
)

LUA_KEYWORDS = (
    "and break do else elseif end false for function goto if in local nil not or repeat "
    "return then true until while"
)

HASH_KEYWORDS = (
    "if then else elif fi for while do done in case esac function return local export "
    "def end class module require true false nil"
)

DOCKER_KEYWORDS = (
    "FROM RUN CMD LABEL EXPOSE ENV ADD COPY ENTRYPOINT VOLUME USER WORKDIR ARG ONBUILD "
    "STOPSIGNAL HEALTHCHECK SHELL AS"
)

SQL_KEYWORDS = (
    "select from where insert update delete into values join on group by "
    "order limit create table alter drop index and or not null as"
)


@dataclass(frozen=True)
class Syntax:
    comment: str = None
    keywords: str = ""
    strings: str = STRING_PATTERN
    numbers: bool = True
    extras: tuple = ()


SYNTAXES = {
    "c": Syntax(C_COMMENT, C_KEYWORDS, QUOTED_PATTERN, extras=(("k", r"^\s*#\s*\w+"),)),
    "cpp": Syntax(C_COMMENT, CPP_KEYWORDS, QUOTED_PATTERN, extras=(("k", r"^\s*#\s*\w+"),)),
    "go": Syntax(C_COMMENT, GO_KEYWORDS),
    "zig": Syntax(SLASH_COMMENT, ZIG_KEYWORDS, QUOTED_PATTERN,
                  extras=(("k", r"@\w+"), ("s", r"\\\\.*"))),
    "py": Syntax(HASH_COMMENT, PYTHON_KEYWORDS, TRIPLE_QUOTED_PATTERN + "|" + QUOTED_PATTERN,
                 extras=(("k", r"^\s*@[\w.]+"),)),
    "clike": Syntax(C_COMMENT, CLIKE_KEYWORDS),
    "lua": Syntax(r"--.*", LUA_KEYWORDS, QUOTED_PATTERN),
    "hash": Syntax(HASH_COMMENT, HASH_KEYWORDS),
    "dockerfile": Syntax(HASH_COMMENT, DOCKER_KEYWORDS),
    "sql": Syntax(r"--.*", SQL_KEYWORDS),
    "json": Syntax(None, "true false null"),
    "css": Syntax(BLOCK_COMMENT, ""),
    "html": Syntax(r"<!--.*?(?:-->|$)", "", TERMINATED_PATTERN, numbers=False,
                   extras=(("k", r"</?[\w:-]+"),)),
    "markdown": Syntax(None, "", None, numbers=False,
                       extras=(("k", r"^\s{0,3}#{1,6}\s.*"), ("s", r"`[^`]+`"))),
    "generic": Syntax(GENERIC_COMMENT, "", DOUBLE_QUOTED_PATTERN),
}

EXTENSIONS = {
    "c": "c h",
    "cpp": "cc cpp cxx hpp hh hxx ino",
    "go": "go",
    "zig": "zig zon",
    "py": "py pyi pyw",
    "clike": "js jsx ts tsx mjs cjs java cs rs kt swift php scala dart",
    "lua": "lua",
    "hash": "sh bash zsh yml yaml toml rb pl r mk makefile conf ini",
    "dockerfile": "dockerfile containerfile",
    "sql": "sql",
    "json": "json jsonc",
    "css": "css scss less",
    "html": "html htm xhtml xml svg",
    "markdown": "md markdown",
}

PLAIN_EXTENSIONS = ("txt", "log")
GENERIC_LANGUAGE = "generic"

LANGUAGE_BY_EXTENSION = {ext: lang for lang, exts in EXTENSIONS.items() for ext in exts.split()}


def build_tokenizer(syntax):
    parts = []
    if syntax.comment:
        parts.append(f"(?P<c>{syntax.comment})")
    parts += [f"(?P<{kind}_{index}>{pattern})" for index, (kind, pattern) in enumerate(syntax.extras)]
    if syntax.strings:
        parts.append(f"(?P<s>{syntax.strings})")
    if syntax.numbers:
        parts.append(f"(?P<n>{NUMBER_PATTERN})")
    if syntax.keywords:
        parts.append(r"(?P<k>\b(?:%s)\b)" % "|".join(syntax.keywords.split()))
    return re.compile("|".join(parts))


TOKENIZERS = {lang: build_tokenizer(syntax) for lang, syntax in SYNTAXES.items()}


def extension_of(path):
    base = os.path.basename(path).lower()
    return base.rsplit(".", 1)[-1] if "." in base else base


def language_of(path):
    extension = extension_of(path)
    if extension in PLAIN_EXTENSIONS:
        return None
    return LANGUAGE_BY_EXTENSION.get(extension, GENERIC_LANGUAGE)


def token_kinds(text, lang):
    kinds = [None] * len(text)
    tokenizer = TOKENIZERS.get(lang)
    if not tokenizer:
        return kinds
    for match in tokenizer.finditer(text):
        kinds[match.start():match.end()] = [match.lastgroup[0]] * (match.end() - match.start())
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
