import hashlib
import json
import os
from datetime import datetime

from scr_diff import Status, parse_diff
from scr_git import OUT_DIR, detect_base, git
from scr_html import esc, fill, load_template
from scr_render import Expand, build_view, warnings_html

ALL_VIEW = "all"
LIVE_SUFFIX = ".live.js"
STATUS_FILTERS = tuple(Status)
ID_LENGTH = 12
DAY_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H%M"


def hidden_attr(view_id):
    return "" if view_id == ALL_VIEW else " hidden"


def commit_shas(repo, base):
    commit_base = base or detect_base(repo)
    if not commit_base:
        raise SystemExit("--commits: could not detect a base branch; pass --base <ref>.")
    merge_base = git(repo, "merge-base", commit_base, "HEAD").strip()
    return git(repo, "rev-list", "--reverse", "--no-merges", f"{merge_base}..HEAD").split()


def build_views(repo, diff_text, since, base, with_commits, file_template):
    views = [{"id": ALL_VIEW, "label": "Since last pass" if since else "All changes"}]
    built = {ALL_VIEW: build_view(ALL_VIEW, parse_diff(diff_text), repo, Expand.ALLOWED, file_template)}
    if not with_commits:
        return views, built

    for index, sha in enumerate(commit_shas(repo, base)):
        view_id = f"c{index}"
        subject = git(repo, "log", "-1", "--format=%s", sha).strip()
        commit_diff = git(repo, "show", "--format=", "--no-color", "-M", "-U3", sha)
        views.append({"id": view_id, "label": f"{sha[:7]} {subject}"})
        built[view_id] = build_view(view_id, parse_diff(commit_diff), repo, Expand.NONE, file_template)
    return views, built


def render_tabs(views, built):
    if len(views) == 1:
        return ""
    buttons = "".join(
        f'<button class="tab{" active" if view["id"] == ALL_VIEW else ""}" data-view="{view["id"]}">'
        f'{esc(view["label"])} <small>{built[view["id"]].files}</small></button>'
        for view in views)
    return f'<div class="tabs" id="tabs">{buttons}</div>'


def render_views(views, built):
    return "".join(
        f'<div class="view" id="view-{view["id"]}" data-view="{view["id"]}"{hidden_attr(view["id"])}>'
        f'{built[view["id"]].html}</div>' for view in views)


def render_nav(views, built):
    return "".join(
        f'<div class="navlist" data-view="{view["id"]}"{hidden_attr(view["id"])}>'
        f'{built[view["id"]].nav}</div>' for view in views)


def report_stamp(head, compare, views, built):
    content = head + compare + warnings_html(built[ALL_VIEW].findings)
    content += "".join(built[view["id"]].html for view in views)
    return hashlib.sha1(content.encode()).hexdigest()


def build_meta(repo, branch, head, base, compare, views):
    identity = f"{repo}|{head}|{base or ''}"
    return {"id": hashlib.sha1(identity.encode()).hexdigest()[:ID_LENGTH],
            "repo": os.path.basename(repo), "branch": branch, "head": head,
            "compare": compare, "views": views}


def render_page(snapshot, meta, views, built):
    overview = built[ALL_VIEW]
    data = json.dumps({"meta": meta, "src": overview.sources}).replace("<", "\\u003c")
    statuses = "".join(f'<button class="chip" data-status="{status}">{status}</button>'
                       for status in STATUS_FILTERS)
    return fill(load_template("report.html"),
                title=esc(f"Code review {meta['head']}"), snapshot=snapshot,
                css=f"<style>{load_template('report.css')}</style>",
                js=f"<script>{load_template('report.js')}</script>",
                repo=esc(meta["repo"]), branch=esc(meta["branch"]), head=esc(meta["head"]),
                compare=esc(meta["compare"]), files=str(overview.files),
                adds=str(overview.added), dels=str(overview.removed),
                generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                warnings=warnings_html(overview.findings), statuses=statuses,
                nav=render_nav(views, built), tabs=render_tabs(views, built),
                views=render_views(views, built),
                data=f'<script type="application/json" id="scr-data">{data}</script>')


def write_atomic(path, text):
    temp_path = f"{path}.tmp{os.getpid()}"
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temp_path, path)


def unique_path(directory, stem):
    path, attempt = os.path.join(directory, stem + ".html"), 2
    while os.path.exists(path):
        path, attempt = os.path.join(directory, f"{stem}_{attempt}.html"), attempt + 1
    return path


def default_output(repo, head, since):
    now = datetime.now()
    day = now.strftime(DAY_FORMAT)
    directory = os.path.join(repo, OUT_DIR, day)
    os.makedirs(directory, exist_ok=True)
    stem = f"{day}_{now.strftime(TIME_FORMAT)}_{head}" + ("_since" if since else "")
    return unique_path(directory, stem)
