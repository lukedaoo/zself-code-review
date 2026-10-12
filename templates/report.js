(() => {
    "use strict";

    const DATA = JSON.parse(document.getElementById("scr-data").textContent);
    const META = DATA.meta;
    const SOURCES = DATA.src;

    const ALL_VIEW = "all";
    const LAYOUT_UNIFIED = "unified";
    const THEME_AUTO = "auto";
    const STORAGE_KEY = { review: "scr:" + META.id, layout: "scr:layout", theme: "scr:theme" };
    const UNIFIED_COLUMNS = 3;
    const SPLIT_COLUMNS = 4;
    const EXPAND_STEP = 20;
    const MIN_QUERY_LENGTH = 2;
    const MAX_HITS = 500;
    const MAX_SNIPPET_LENGTH = 200;
    const LIVE_POLL_MS = 2000;
    const COPY_FEEDBACK_MS = 1500;
    const TEXT_INPUT_TAGS = /INPUT|TEXTAREA/;
    const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" };

    const find = (selector, root = document) => root.querySelector(selector);
    const findAll = (selector, root = document) => [...root.querySelectorAll(selector)];
    const escapeHtml = text => String(text).replace(/[&<>"]/g, char => HTML_ESCAPES[char]);

    const flash = element => {
        element.classList.remove("flash");
        void element.offsetWidth;
        element.classList.add("flash");
    };

    const columnsOf = row =>
        row.closest("table").classList.contains("split") ? SPLIT_COLUMNS : UNIFIED_COLUMNS;

    const storage = {
        read(key, fallback) {
            try { return localStorage.getItem(key) || fallback; } catch (error) { return fallback; }
        },
        write(key, value) {
            try { localStorage.setItem(key, value); } catch (error) { }
        },
    };

    const review = {
        notes: {},
        viewed: {},

        load() {
            try {
                const saved = JSON.parse(storage.read(STORAGE_KEY.review, "{}"));
                this.notes = saved.comments || this.notes;
                this.viewed = saved.viewed || this.viewed;
            } catch (error) { }
        },

        save() {
            storage.write(STORAGE_KEY.review, JSON.stringify({ comments: this.notes, viewed: this.viewed }));
        },
    };

    const sections = findAll("section.file");
    let currentView = ALL_VIEW;

    const fileKeyOf = section => section.dataset.fkey;
    const sectionFor = fileKey => sections.find(section => fileKeyOf(section) === fileKey);
    const sectionsInView = () => sections.filter(section => section.dataset.view === currentView);
    const navLinkFor = section => findAll(".navlink").find(link => link.dataset.fkey === fileKeyOf(section));
    const activeLayout = () => document.body.dataset.layout;
    const activeDiff = section => find(".diff." + activeLayout(), section);
    const rowFor = (lineKey, root) => find(`tr[data-k~="${lineKey}"]`, root);

    const layout = {
        set(name) {
            document.body.dataset.layout = name;
            findAll(".seg button").forEach(button => button.classList.toggle("on", button.dataset.layout === name));
            storage.write(STORAGE_KEY.layout, name);
            search.markHits();
        },

        restore() {
            this.set(storage.read(STORAGE_KEY.layout, LAYOUT_UNIFIED));
        },
    };

    const theme = {
        set(name) {
            if (name === THEME_AUTO) {
                document.documentElement.removeAttribute("data-theme");
            } else {
                document.documentElement.dataset.theme = name;
            }
            find("#theme").value = name;
            storage.write(STORAGE_KEY.theme, name);
        },

        restore() {
            this.set(storage.read(STORAGE_KEY.theme, THEME_AUTO));
        },
    };

    const views = {
        show(id) {
            currentView = id;
            findAll(".view, .navlist").forEach(element => element.hidden = element.dataset.view !== id);
            findAll(".tab").forEach(tab => tab.classList.toggle("active", tab.dataset.view === id));
            filters.apply();
        },
    };

    const viewed = {
        syncSection(section) {
            const isViewed = !!review.viewed[fileKeyOf(section)];
            find(".viewed-cb", section).checked = isViewed;
            const link = navLinkFor(section);
            if (link) link.classList.toggle("done", isViewed);
        },

        setSection(section, isViewed) {
            if (isViewed) {
                review.viewed[fileKeyOf(section)] = true;
            } else {
                delete review.viewed[fileKeyOf(section)];
            }
            section.classList.toggle("collapsed", isViewed);
            this.syncSection(section);
            review.save();
            filters.apply();
        },

        updateProgress() {
            const inView = sectionsInView();
            const count = inView.filter(section => review.viewed[fileKeyOf(section)]).length;
            find("#progress").textContent = `Viewed ${count}/${inView.length}`;
        },

        collapseInitial() {
            for (const section of sections) {
                this.syncSection(section);
                const isGenerated = section.dataset.generated === "1";
                if (review.viewed[fileKeyOf(section)] || isGenerated) section.classList.add("collapsed");
            }
        },
    };

    const notes = {
        idFor(section, lineKey) {
            return fileKeyOf(section) + "#" + lineKey;
        },

        label(lineKey) {
            return (lineKey[0] === "o" ? "old " : "") + "L" + lineKey.slice(1);
        },

        inSection(section) {
            return Object.values(review.notes).filter(note => note.fkey === fileKeyOf(section));
        },

        sorted() {
            const byLine = (a, b) => a.path.localeCompare(b.path) || (+a.key.slice(1)) - (+b.key.slice(1));
            return Object.values(review.notes).sort(byLine);
        },

        lineText(row, lineKey) {
            const numberCell = row.querySelector(`td.ln[data-key="${lineKey}"]`);
            let cell = numberCell && numberCell.nextElementSibling;
            while (cell && !cell.classList.contains("code")) cell = cell.nextElementSibling;
            const content = cell && cell.querySelector(".cc");
            return content ? content.textContent : "";
        },

        rowHtml(note, columns, isOutdated) {
            const outdatedTag = isOutdated
                ? `<span class="tag-out" title="The line text differs from when the note was written">outdated?</span>`
                : "";
            return `<tr class="cmt"><td colspan="${columns}"><div class="cbox${note.done ? " done" : ""}" data-ck="${escapeHtml(note.ck)}">` +
                `<input type="checkbox" class="cdone" title="Mark as addressed"${note.done ? " checked" : ""}>` +
                `<div class="ctext">${escapeHtml(note.text)}</div>` +
                outdatedTag +
                `<span class="cact"><button data-act="edit">Edit</button><button data-act="del">Delete</button></span></div></td></tr>`;
        },

        renderIn(section) {
            findAll("tr.cmt", section).forEach(row => row.remove());
            for (const note of this.inSection(section)) {
                for (const table of findAll("table.diff", section)) {
                    const row = rowFor(note.key, table);
                    if (!row) continue;
                    const isOutdated = this.lineText(row, note.key).trim() !== note.snippet.trim();
                    row.insertAdjacentHTML("afterend", this.rowHtml(note, columnsOf(row), isOutdated));
                }
            }
        },

        changed(section) {
            review.save();
            this.renderIn(section);
            notesPanel.render();
            filters.apply();
        },

        remove(section, id) {
            delete review.notes[id];
            this.changed(section);
        },

        openEditor(section, row, lineKey) {
            findAll("tr.cedit").forEach(editorRow => editorRow.remove());
            const id = this.idFor(section, lineKey);
            const existing = review.notes[id];
            row.insertAdjacentHTML("afterend",
                `<tr class="cedit"><td colspan="${columnsOf(row)}"><textarea placeholder="Note for ${this.label(lineKey)}… (Ctrl+Enter to save, Esc to cancel)"></textarea>` +
                `<div class="row"><button class="save">Save</button><button class="cancel">Cancel</button></div></td></tr>`);

            const editorRow = row.nextElementSibling;
            const textarea = find("textarea", editorRow);
            textarea.value = existing ? existing.text : "";
            textarea.focus();

            const close = () => editorRow.remove();
            const commit = () => {
                const text = textarea.value.trim();
                if (text) {
                    review.notes[id] = {
                        ck: id, fkey: fileKeyOf(section), view: section.dataset.view, path: section.dataset.path,
                        key: lineKey, text, done: existing ? existing.done : false,
                        snippet: this.lineText(row, lineKey).slice(0, MAX_SNIPPET_LENGTH),
                    };
                } else {
                    delete review.notes[id];
                }
                close();
                this.changed(section);
            };

            find(".save", editorRow).onclick = commit;
            find(".cancel", editorRow).onclick = close;
            textarea.onkeydown = event => {
                if (event.key === "Escape") close();
                else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) commit();
            };
        },

        editExisting(note) {
            const section = sectionFor(note.fkey);
            const row = rowFor(note.key, activeDiff(section));
            if (row) this.openEditor(section, row, note.key);
        },

        toggleDone(note, isDone) {
            note.done = isDone;
            review.save();
            notesPanel.render();
            const section = sectionFor(note.fkey);
            if (section) this.renderIn(section);
        },

        clearAll() {
            if (!Object.keys(review.notes).length || !confirm("Delete all notes for this review?")) return;
            review.notes = {};
            review.save();
            sections.forEach(section => this.renderIn(section));
            notesPanel.render();
            filters.apply();
        },
    };

    const notesPanel = {
        render() {
            const all = notes.sorted();
            find("#notes-count").textContent = all.length;
            find("#notes-list").innerHTML = all.map(note =>
                `<li class="nitem${note.done ? " done" : ""}" data-ck="${escapeHtml(note.ck)}">` +
                `<input type="checkbox" class="ndone"${note.done ? " checked" : ""}> ` +
                `<a href="#" data-goto="1" data-view="${escapeHtml(note.view)}" data-fkey="${escapeHtml(note.fkey)}" data-key="${note.key}">${escapeHtml(note.path)}:${notes.label(note.key)}</a>` +
                ` <span class="nact"><button data-act="ndel">delete</button></span>` +
                `<code>${escapeHtml(note.snippet)}</code><div class="ntext">${escapeHtml(note.text)}</div></li>`).join("") ||
                `<li class="muted small">No notes yet.</li>`;
        },

        toMarkdown() {
            let markdown = `# Review notes — ${META.repo} @ ${META.branch} (${META.head})\n\n_${META.compare}_\n`;
            let lastFileKey = null;
            for (const note of notes.sorted()) {
                if (note.fkey !== lastFileKey) {
                    const view = META.views.find(candidate => candidate.id === note.view);
                    const commitLabel = note.view !== ALL_VIEW ? `  _(commit ${view ? view.label : note.view})_` : "";
                    markdown += `\n## ${note.path}${commitLabel}\n`;
                    lastFileKey = note.fkey;
                }
                const snippet = note.snippet.trim().replace(/`/g, "'");
                const body = note.text.split("\n").map(line => "  " + line).join("\n");
                markdown += `\n- [${note.done ? "x" : " "}] **${notes.label(note.key)}** \`${snippet}\`\n${body}\n`;
            }
            return markdown;
        },

        copyText(text) {
            if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
            const textarea = document.createElement("textarea");
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            textarea.remove();
        },

        copyMarkdown(button) {
            Promise.resolve(this.copyText(this.toMarkdown())).then(() => {
                button.textContent = "Copied ✓";
                setTimeout(() => button.textContent = "Copy .md", COPY_FEEDBACK_MS);
            });
        },

        downloadMarkdown() {
            const link = document.createElement("a");
            link.href = URL.createObjectURL(new Blob([this.toMarkdown()], { type: "text/markdown" }));
            link.download = `review-notes-${META.head}.md`;
            link.click();
            URL.revokeObjectURL(link.href);
        },

        toggle() {
            const panel = find("#notes");
            panel.hidden = !panel.hidden;
        },

        close() {
            find("#notes").hidden = true;
        },
    };

    const context = {
        rowHtml(isSplit, newNo, oldNo, html) {
            const key = "n" + newNo;
            const code = `<td class="code"><span class="sign"> </span><span class="cc">${html}</span></td>`;
            const oldCell = `<td class="ln" data-key="${key}">${oldNo}</td>`;
            const newCell = `<td class="ln" data-key="${key}">${newNo}</td>`;
            return isSplit
                ? `<tr class="ctx exp" data-k="${key}">${oldCell}${code}${newCell}${code}</tr>`
                : `<tr class="ctx exp" data-k="${key}">${oldCell}${newCell}${code}</tr>`;
        },

        shrinkGap(gapRow, mode, first, last) {
            if (mode === "top") {
                gapRow.dataset.s = last + 1;
            } else if (mode === "bottom") {
                gapRow.dataset.e = first - 1;
            } else {
                gapRow.dataset.e = gapRow.dataset.s - 1;
            }

            const start = +gapRow.dataset.s;
            const end = +gapRow.dataset.e;
            if (start > end) {
                if (gapRow.classList.contains("tail")) {
                    gapRow.remove();
                } else {
                    const buttons = find(".exp-btns", gapRow);
                    if (buttons) buttons.remove();
                }
                return;
            }

            const hidden = end - start + 1;
            const allButton = find("[data-mode=all]", gapRow);
            if (allButton) allButton.textContent = "↕ " + hidden;
            if (hidden <= EXPAND_STEP) {
                findAll("[data-mode=top],[data-mode=bottom]", gapRow).forEach(button => button.remove());
            }
        },

        expand(button) {
            const gapRow = button.closest("tr");
            const section = gapRow.closest("section.file");
            const source = SOURCES[fileKeyOf(section)];
            if (!source) return;

            const start = +gapRow.dataset.s;
            const end = +gapRow.dataset.e;
            const offset = +gapRow.dataset.off;
            const mode = button.dataset.mode;
            const first = mode === "bottom" ? Math.max(start, end - EXPAND_STEP + 1) : start;
            const last = mode === "top" ? Math.min(end, start + EXPAND_STEP - 1) : end;

            for (const row of findAll(`tr[data-gid="${gapRow.dataset.gid}"]`, section)) {
                const isSplit = row.closest("table").classList.contains("split");
                let html = "";
                for (let lineNo = first; lineNo <= last; lineNo++) {
                    html += this.rowHtml(isSplit, lineNo, lineNo + offset, source[lineNo - 1]);
                }
                row.insertAdjacentHTML(mode === "bottom" ? "afterend" : "beforebegin", html);
                this.shrinkGap(row, mode, first, last);
            }

            search.forget(section);
            notes.renderIn(section);
        },
    };

    const filters = {
        query: "",
        statuses: new Set(),
        unviewedOnly: false,
        commentedOnly: false,

        normalizedQuery() {
            return this.query.trim().toLowerCase();
        },

        toggleStatus(status) {
            if (this.statuses.has(status)) this.statuses.delete(status);
            else this.statuses.add(status);
            return this.statuses.has(status);
        },

        accepts(section, query) {
            if (section.dataset.view !== currentView) return false;
            if (this.statuses.size && !this.statuses.has(section.dataset.status)) return false;
            if (this.unviewedOnly && review.viewed[fileKeyOf(section)]) return false;
            if (this.commentedOnly && !notes.inSection(section).length) return false;
            if (!query) return true;
            return section.dataset.path.toLowerCase().includes(query) ||
                (query.length >= MIN_QUERY_LENGTH && search.sectionText(section).includes(query));
        },

        apply() {
            const query = this.normalizedQuery();
            for (const section of sections) {
                const isVisible = this.accepts(section, query);
                section.hidden = !isVisible;
                const link = navLinkFor(section);
                if (link) link.hidden = !isVisible;
            }
            search.markHits();
            viewed.updateProgress();
        },
    };

    const search = {
        rows: [],
        index: -1,
        textCache: new WeakMap(),

        sectionText(section) {
            if (!this.textCache.has(section)) {
                const text = findAll(".diff.unified td.code .cc", section).map(cell => cell.textContent).join("\n");
                this.textCache.set(section, text.toLowerCase());
            }
            return this.textCache.get(section);
        },

        forget(section) {
            this.textCache.delete(section);
        },

        collectHits(query) {
            const selector = ".diff." + activeLayout() + " td.code .cc";
            for (const section of sections) {
                if (section.dataset.view !== currentView || section.hidden) continue;
                for (const cell of findAll(selector, section)) {
                    if (cell.textContent.toLowerCase().includes(query)) {
                        const row = cell.closest("tr");
                        row.classList.add("hit");
                        this.rows.push(row);
                    }
                    if (this.rows.length > MAX_HITS) break;
                }
            }
        },

        markHits() {
            findAll("tr.hit").forEach(row => row.classList.remove("hit"));
            this.rows = [];
            this.index = -1;

            const query = filters.normalizedQuery();
            const isSearching = query.length >= MIN_QUERY_LENGTH;
            if (isSearching) this.collectHits(query);

            const count = this.rows.length;
            find("#hits").textContent = isSearching ? `${count} match${count === 1 ? "" : "es"}` : "";
        },

        jump(direction) {
            if (!this.rows.length) return;
            this.index = (this.index + direction + this.rows.length) % this.rows.length;
            const row = this.rows[this.index];
            row.closest("section.file").classList.remove("collapsed");
            row.scrollIntoView({ block: "center" });
            flash(row);
            find("#hits").textContent = `${this.index + 1}/${this.rows.length}`;
        },
    };

    const goTo = (view, fileKey, lineKey) => {
        if (view !== currentView) views.show(view);
        const section = sectionFor(fileKey);
        if (!section) return;
        section.hidden = false;
        section.classList.remove("collapsed");
        const row = lineKey ? rowFor(lineKey, activeDiff(section)) : null;
        const target = row || section;
        target.scrollIntoView({ block: "center" });
        flash(target);
    };

    const clickHandlers = [
        ["td.ln[data-key]", (cell) => {
            const row = cell.closest("tr");
            notes.openEditor(row.closest("section.file"), row, cell.dataset.key);
        }],
        [".exp-btn", (button) => context.expand(button)],
        ["[data-goto]", (link, event) => {
            event.preventDefault();
            goTo(link.dataset.view, link.dataset.fkey, link.dataset.key);
        }],
        [".cact button, .nact button", (button) => {
            const id = button.closest("[data-ck]").dataset.ck;
            const note = review.notes[id];
            if (!note) return;
            if (button.dataset.act === "edit") notes.editExisting(note);
            else notes.remove(sectionFor(note.fkey), id);
        }],
        [".fhead", (header, event) => {
            if (event.target.closest("label")) return;
            header.closest("section.file").classList.toggle("collapsed");
        }],
        [".seg button", (button) => layout.set(button.dataset.layout)],
    ];

    const onDocumentClick = event => {
        for (const [selector, handle] of clickHandlers) {
            const element = event.target.closest(selector);
            if (!element) continue;
            handle(element, event);
            return;
        }
    };

    const onDocumentChange = event => {
        const target = event.target;
        if (target.matches(".viewed-cb")) {
            viewed.setSection(target.closest("section.file"), target.checked);
            return;
        }
        if (target.matches(".cdone, .ndone")) {
            const note = review.notes[target.closest("[data-ck]").dataset.ck];
            if (note) notes.toggleDone(note, target.checked);
        }
    };

    const bindFilters = () => {
        findAll(".chips .chip").forEach(chip => chip.addEventListener("click", () => {
            const isOn = filters.toggleStatus(chip.dataset.status);
            chip.classList.toggle("on", isOn);
            filters.apply();
        }));

        const bindToggle = (selector, flag) => find(selector).addEventListener("click", event => {
            filters[flag] = !filters[flag];
            event.currentTarget.classList.toggle("on", filters[flag]);
            filters.apply();
        });
        bindToggle("#f-unviewed", "unviewedOnly");
        bindToggle("#f-commented", "commentedOnly");

        find("#collapse-all").addEventListener("click", () =>
            sectionsInView().forEach(section => section.classList.add("collapsed")));
        find("#expand-all").addEventListener("click", () =>
            sectionsInView().forEach(section => section.classList.remove("collapsed")));
    };

    const bindSearch = () => {
        const input = find("#q");
        input.addEventListener("input", () => {
            filters.query = input.value;
            filters.apply();
        });
        input.addEventListener("keydown", event => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            search.jump(event.shiftKey ? -1 : 1);
        });
        document.addEventListener("keydown", event => {
            if (event.key !== "/" || TEXT_INPUT_TAGS.test(document.activeElement.tagName)) return;
            event.preventDefault();
            input.focus();
        });
    };

    const bindNotesPanel = () => {
        find("#notes-btn").addEventListener("click", () => notesPanel.toggle());
        find("#notes-close").addEventListener("click", () => notesPanel.close());
        find("#notes-copy").addEventListener("click", event => notesPanel.copyMarkdown(event.currentTarget));
        find("#notes-dl").addEventListener("click", () => notesPanel.downloadMarkdown());
        find("#notes-clear").addEventListener("click", () => notes.clearAll());
    };

    const bindEvents = () => {
        find("#theme").addEventListener("change", event => theme.set(event.target.value));
        const tabs = find("#tabs");
        if (tabs) {
            tabs.addEventListener("click", event => {
                const tab = event.target.closest(".tab");
                if (tab) views.show(tab.dataset.view);
            });
        }
        document.addEventListener("click", onDocumentClick);
        document.addEventListener("change", onDocumentChange);
        bindFilters();
        bindSearch();
        bindNotesPanel();
    };

    const startLiveReload = () => {
        if (!META.live) return;
        const badge = find("#live");
        badge.hidden = false;
        setInterval(() => {
            const script = document.createElement("script");
            script.src = META.live + "?t=" + Date.now();
            script.onload = () => {
                script.remove();
                if (!window.__SCR_STAMP || window.__SCR_STAMP === META.stamp) return;
                if (find(".cedit textarea")) badge.textContent = " update pending (finish your note)";
                else location.reload();
            };
            script.onerror = () => script.remove();
            document.head.appendChild(script);
        }, LIVE_POLL_MS);
    };

    const keepToolbarHeightVar = () => {
        const toolbar = find(".toolbar");
        const update = () => document.documentElement.style.setProperty("--tb", toolbar.offsetHeight + "px");
        update();
        window.addEventListener("resize", update);
        if (window.ResizeObserver) new ResizeObserver(update).observe(toolbar);
    };

    const init = () => {
        review.load();
        layout.restore();
        theme.restore();
        viewed.collapseInitial();
        bindEvents();
        startLiveReload();
        keepToolbarHeightVar();
        sections.forEach(section => notes.renderIn(section));
        notesPanel.render();
        filters.apply();
    };

    init();
})();
