import html
import os
import re
import sys

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "templates")
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def esc(text):
    return html.escape(text, quote=True)


def load_template(name):
    path = os.path.join(TEMPLATE_DIR, name)
    if not os.path.isfile(path):
        sys.exit(f"Missing template: {path}")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def fill(template, **values):
    return PLACEHOLDER_RE.sub(lambda match: values.get(match.group(1), match.group(0)), template)
