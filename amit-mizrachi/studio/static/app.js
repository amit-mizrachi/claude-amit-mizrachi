/* Project Studio - the page script. It only draws what the server sends: the HomeState (GET /state
   and the `state` events of GET /events), at #/p/<id> the ProjectView (GET /project?id=, read
   again on every `state` event), at #/inbox the Inbox drawer (GET /inbox) beside the cards, and the
   "Move to..." / "Set parent" picker (GET /choices?id=). The order, the texts and every status word
   come from the SDK (studio/sdk/home.py, projectview.py, inboxview.py); an action POSTs ids, never
   a URL, path or command. No ranking, sorting or status rule lives here: the home rows keep the
   SDK's `order` from the load on, until "Re-sort". All text goes in through textContent, never as
   HTML. Live re-ordering waits while a drag or the picker is open. */
(function () {
  "use strict";

  var THEME_KEY = "project-studio-theme";
  var root = document.documentElement;

  function stored() {
    try { return window.localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }
  function store(value) {
    try { window.localStorage.setItem(THEME_KEY, value); } catch (e) { /* private window: not kept */ }
  }
  var saved = stored();
  if (saved === "light" || saved === "dark") { root.setAttribute("data-theme", saved); }

  // CSS class names of the mockup, per SDK status word and card attention.
  var TONE = { "needs-you": "wait", blocked: "blk", running: "run_", "in-review": "rev", merged: "done", done: "done",
    pending: "pend", paused: "pend", unknown: "stale" };
  var ATTENTION = { "needs-you": "attn", blocked: "bad" };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) { if (arguments[i]) { parent.appendChild(arguments[i]); } }
    return parent;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
  function $(id) { return document.getElementById(id); }

  function token() {
    var meta = document.querySelector('meta[name="studio-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Studio-Token": token() },
      body: JSON.stringify(body || {})
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) { throw new Error(data && data.message ? data.message : "Request failed (" + res.status + ")."); }
        return data;
      });
    });
  }

  function reload() {
    return fetch("/state").then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) { throw new Error(data && data.message ? data.message : "Request failed (" + res.status + ")."); }
        return data;
      });
    }).then(render);
  }

  function newProject() {
    var name = window.prompt("Project name");
    if (name === null) { return; }
    post("/api/projects", { name: name }).then(reload).catch(function (err) { window.alert(err.message); });
  }

  function openInbox() { window.location.hash = window.location.hash === "#/inbox" ? "#/" : "#/inbox"; }

  // ------------------------------------------------------------------ components

  function prLine(text) {
    var node = el("span", "pr");
    var match = /^PR (#\d+)(.*)$/.exec(text);
    if (!match) { node.textContent = text; return node; }
    return add(node, document.createTextNode("PR "), el("b", null, match[1]), document.createTextNode(match[2]));
  }

  function bar(cells) {
    var node = el("span", "bar");
    cells.forEach(function (cell) { node.appendChild(el("i", cell || null)); });
    return node;
  }

  // A home run line. A run waiting on you keeps its Open plan, with the buttons its `quick` names
  // beside it (Open conductor); every line has the "..." menu (and right-click), and drags onto
  // another project's row or block to move there. `from` is the project it lives in.
  function runLine(run, from) {
    var tone = TONE[run.status] || "stale";
    var line = el("div", run.gone ? "run dim" : "run");
    var name = el("span", "nm", run.title);
    name.title = run.title;
    add(line, el("span", "g " + tone, run.glyph), name);
    var acts = el("span", "ra");
    if (run.open_plan_url) {
      var plan = el("a", "btn pri", "Open plan");
      plan.href = run.open_plan_url;
      plan.target = "_blank";
      plan.rel = "noopener noreferrer";
      plan.addEventListener("click", function (e) { e.stopPropagation(); });
      acts.appendChild(plan);
    }
    quickButtons(run, acts);
    line.appendChild(add(acts, menuButton(run)));
    withMenu(line, run);
    line.setAttribute("data-item-id", run.item_id);
    draggable(line, { id: run.item_id, name: run.title, revision: null, from: from });
    var st = add(el("span", "st"), el("span", "w " + tone, run.word));
    if (run.sub_project) {
      var tag = el("span", "in", run.sub_project);
      tag.title = run.sub_project;
      st.appendChild(tag);
    }
    if (run.reason) { st.appendChild(el("span", null, run.reason)); }
    if (run.progress) { st.appendChild(el("span", null, run.progress)); }
    if (run.bar && run.bar.length) { st.appendChild(bar(run.bar)); }
    return add(line, st);
  }

  // The runs of a home row or block, laid across the width: several per line, each in a cell of its own.
  function runCells(runs, from) {
    var grid = el("div", "runs");
    runs.forEach(function (run) { grid.appendChild(runLine(run, from || run.sub_project_id)); });
    return grid;
  }

  // A sub-project's block inside its parent's row: its name, status, runs in words, "2 inside", and
  // its runs. A click (or Enter) opens the sub-project, not the row.
  function subBlock(s) {
    var tone = TONE[s.status] || "stale";
    var href = "#/p/" + encodeURIComponent(s.project_id);
    var name = el("span", "nm", s.name);
    name.title = s.name;
    var head = add(el("div", "bh"), el("span", "g " + tone, s.glyph), name,
      s.word ? el("span", "w " + tone, s.word) : null, el("span", "sub", s.text),
      s.inside ? el("span", "sub", s.inside) : null);
    var node = add(el("div", "block"), head, s.runs.length ? runCells(s.runs.map(function (r) {
      return r.sub_project_id ? r : Object.assign({}, r, { sub_project_id: s.project_id });
    })) : null, s.more ? el("span", "more", s.more) : null);
    node.setAttribute("data-project-id", s.project_id);
    dropTarget(node, s.project_id, true);
    node.setAttribute("role", "link");
    node.tabIndex = 0;
    function go(e) { e.stopPropagation(); window.location.hash = href; }
    node.addEventListener("click", go);
    node.addEventListener("keydown", function (e) { if (e.key === "Enter") { go(e); } });
    return node;
  }

  // A project's full-width home row: name, status, runs in words, last activity; its own runs; then
  // a block per active sub-project. Names that do not fit end in "..." and show in full on hover.
  function card(c) {
    var node = el("div", "card prow" + (ATTENTION[c.attention] ? " " + ATTENTION[c.attention] : ""));
    var href = "#/p/" + encodeURIComponent(c.project.id);
    node.setAttribute("data-project-id", c.project.id);
    draggable(node, { id: c.project.id, name: c.project.name, revision: null });
    dropTarget(node, c.project.id);
    node.setAttribute("role", "link");
    node.tabIndex = 0;
    node.addEventListener("click", function () { window.location.hash = href; });
    node.addEventListener("keydown", function (e) { if (e.key === "Enter") { window.location.hash = href; } });
    var title = el("h4", null, c.project.name);
    title.title = c.project.name;
    var tone = TONE[c.status] || "stale";
    node.appendChild(add(el("div", "ct"), el("span", "g " + tone, c.glyph), title,
      c.word ? el("span", "w " + tone, c.word) : null, el("span", "sub", c.counts),
      el("span", "age", c.last_activity)));
    if (c.runs.length) { node.appendChild(runCells(c.runs, c.project.id)); }
    if (c.more) { node.appendChild(el("span", "more", c.more)); }
    if (c.pr) { node.appendChild(prLine(c.pr)); }
    if (c.sub_projects.length) {
      var blocks = el("div", "blocks");
      c.sub_projects.forEach(function (s) { blocks.appendChild(subBlock(s)); });
      node.appendChild(blocks);
    }
    if (c.empty && !c.sub_projects.length) { node.appendChild(el("span", "none", c.empty)); }
    return node;
  }

  function banner(b) {
    var retry = el("button", "btn", "Retry");
    retry.type = "button";
    retry.addEventListener("click", function () {
      retry.disabled = true;
      post("/api/refresh").then(reload).catch(function (err) { window.alert(err.message); })
        .then(function () { retry.disabled = false; });
    });
    var node = add(el("div", "banner"), el("b", null, "!"), el("span", null, b.text), el("span", "sp"), retry);
    node.title = b.error;
    return node;
  }

  function skeleton() {
    var grid = el("div", "prows");
    for (var i = 0; i < 4; i++) {
      grid.appendChild(add(el("div", "card prow"), el("div", "sk w60"), el("div", "sk w90"), el("div", "sk w40")));
    }
    var frag = document.createDocumentFragment();
    return add(frag, grid, el("p", "none loading", "Reading workspaces and sessions..."));
  }

  function firstRun(text) {
    var make = el("button", "btn pri", "+ New project");
    make.type = "button";
    make.addEventListener("click", newProject);
    var inbox = el("button", "btn", "Open Inbox");
    inbox.type = "button";
    inbox.addEventListener("click", openInbox);
    return add(el("div", "empty"), el("p", "lead", "No projects yet"), el("p", "txt", text),
      make, document.createTextNode(" "), inbox);
  }

  // ------------------------------------------------------------------ the project view (#/p/<id>)

  var ARROW = "\u2197 ";
  var current = null;     // the project the view shows, null on the home page
  var lastView = null;
  var popOpen = null;     // "link" or "more" while a header menu is open, "rename" while the name is edited
  var openFolds = {};     // "<project id>:<fold kind>" -> true once opened
  var hot = null;         // the session row just opened in Terminal
  var toastTimer = null;

  function projectId() {
    var match = /^#\/p\/([^\/?]+)$/.exec(window.location.hash);
    return match ? decodeURIComponent(match[1]) : null;
  }

  function button(text, cls, onClick) {
    var node = el("button", "btn" + (cls ? " " + cls : ""), text);
    node.type = "button";
    node.addEventListener("click", function (e) { e.stopPropagation(); onClick(node); });
    return node;
  }

  function legacyCopy(text) {
    var area = el("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(area);
    if (!ok) { throw new Error("Could not copy."); }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () { legacyCopy(text); });
    }
    return new Promise(function (resolve) { legacyCopy(text); resolve(); });
  }

  function dismiss() {
    clear($("toasts"));
    if (hot) { hot = null; if (lastView) { renderView(lastView); } }
  }

  function toast(message, command, bad, canCopy) {
    var box = $("toasts");
    clear(box);
    var node = add(el("div", bad ? "toast err" : "toast"), el("span", null, message));
    if (command) {
      var code = el("code", null, command);
      code.title = command;
      node.appendChild(code);
    }
    node.appendChild(el("span", "sp"));
    if (command && canCopy) {
      var again = el("button", "act", "Copy");
      again.type = "button";
      again.addEventListener("click", function () {
        copyText(command).then(function () { again.textContent = "Copied"; },
          function () { again.textContent = "Copy failed"; });
      });
      node.appendChild(again);
    }
    box.appendChild(node);
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(dismiss, 10000);
  }

  function fail(err) { toast(err.message, null, true, false); }

  function openItem(itemId, target, btn) {
    btn.disabled = true;
    post("/api/open", { item_id: itemId, target: target }).then(function (r) {
      if (!r.opened) { toast(r.message, null, true, false); }
    }).catch(fail).then(function () { btn.disabled = false; });
  }

  function openInTerminal(itemId, btn) {
    btn.disabled = true;
    post("/api/terminal", { item_id: itemId }).then(function (r) {
      if (!r.needs_confirm) { return r; }
      if (!window.confirm(r.message)) { return null; }
      return post("/api/terminal", { item_id: itemId, confirmed: true });
    }).then(function (r) {
      if (!r) { return; }
      hot = r.opened ? r.command.item_id : null;
      if (lastView) { renderView(lastView); }
      toast(r.message, r.command.command, !r.opened, r.opened || !r.copied);
    }).catch(fail).then(function () { btn.disabled = false; });
  }

  function copyCommand(itemId) {
    post("/api/command", { item_id: itemId }).then(function (c) {
      return copyText(c.command).then(function () { toast("Command copied:", c.command, false, false); },
        function () { toast("Could not copy. The command:", c.command, true, false); });
    }).catch(fail);
  }

  function closePop() {
    popOpen = null;
    if (lastView) { renderView(lastView); }
  }

  function togglePop(name) {
    popOpen = popOpen === name ? null : name;
    renderView(lastView);
  }

  function linkMenu(v) {
    var wrap = add(el("span", "menu"), button("Link...", null, function () { togglePop("link"); }));
    if (popOpen !== "link") { return wrap; }
    var pop = el("div", "pop");
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
    if (!v.link_choices.length) {
      pop.appendChild(el("span", "none", "No other project to link."));
      return add(wrap, pop);
    }
    var pick = el("select");
    pick.setAttribute("aria-label", "Project to link");
    v.link_choices.forEach(function (c) {
      var option = el("option", null, c.name);
      option.value = c.id;
      pick.appendChild(option);
    });
    var go = button("Link", "pri", function () {
      go.disabled = true;
      post("/api/link", { project_id: v.project.id, other_id: pick.value }).then(function () {
        popOpen = null;
        return loadView(v.project.id);
      }).catch(fail).then(function () { go.disabled = false; });
    });
    return add(wrap, add(pop, pick, add(el("div", "row2"), button("Cancel", "ghost", closePop), go)));
  }

  // Rename edits the name in place: Enter saves, Esc (or a click elsewhere) cancels.
  function startRename() {
    popOpen = "rename";
    renderView(lastView);
    var box = $("rename-box");
    if (box) { box.focus(); box.select(); }
  }

  function nameField(v) {
    var box = el("input", "rename");
    box.id = "rename-box";
    box.type = "text";
    box.value = v.project.name;
    box.maxLength = 120;
    box.setAttribute("aria-label", "Project name (Enter saves, Esc cancels)");
    box.addEventListener("click", function (e) { e.stopPropagation(); });
    box.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePop(); }
      if (e.key === "Enter") { e.preventDefault(); saveName(v, box); }
    });
    return box;
  }

  function saveName(v, box) {
    if (box.value.trim() === v.project.name) { closePop(); return; }
    box.disabled = true;
    post("/api/rename", { project_id: v.project.id, name: box.value }).then(function () {
      popOpen = null;
      return reload().then(function () { return loadView(v.project.id); });
    }).catch(function (err) { box.disabled = false; box.focus(); fail(err); });
  }

  // Remove project... : the server says what is inside and where it goes, the dialog lists it, and
  // only an OK sends the confirmed call. Then the page goes to the parent (or home) with the Undo toast.
  function removeProject(v) {
    closePop();
    post("/api/remove-project", { project_id: v.project.id }).then(function (r) {
      if (!window.confirm(r.message)) { return null; }
      return post("/api/remove-project", { project_id: v.project.id, confirmed: true });
    }).then(function (r) {
      if (!r) { return; }
      window.location.hash = r.parent_id ? "#/p/" + encodeURIComponent(r.parent_id) : "#/";
      moved(r);
      afterMove();
    }).catch(fail);
  }

  // The way back: "< Projects" from a top-level project, "< <parent>" from a sub-project. Esc and
  // the browser's Back go the same way (every view is its own #/p/<id> history entry).
  function backHash(v) {
    var up = v.crumbs[v.crumbs.length - 1];
    return up ? "#/p/" + encodeURIComponent(up.id) : "#/";
  }

  function backButton(v) {
    var up = v.crumbs[v.crumbs.length - 1];
    var node = button("< " + (up ? up.name : "Projects"), "ghost back", function () { window.location.hash = backHash(v); });
    node.title = "Back (Esc)";
    return node;
  }

  function escapeBack(e) {
    if (e.key !== "Escape" || e.defaultPrevented || !current || !lastView || picking) { return; }
    if (popOpen) { closePop(); return; }
    var tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") { return; }
    window.location.hash = backHash(lastView);
  }

  function archive(v) {
    closePop();
    if (!window.confirm("Archive " + v.project.name + "? It and everything under it leave the lists. Nothing is deleted.")) { return; }
    post("/api/archive", { project_id: v.project.id }).then(function () {
      window.location.hash = "#/";
      return reload().then(function () { toast("Archived " + v.project.name, null, false, false); });
    }).catch(fail);
  }

  function unarchive(id, name, btn) {
    if (btn) { btn.disabled = true; }
    post("/api/unarchive", { project_id: id }).then(function () {
      return reload().then(function () {
        toast("Unarchived " + name, null, false, false);
        if (current) { return loadView(current); }
      });
    }).catch(function (err) { if (btn) { btn.disabled = false; } fail(err); });
  }

  function unlink(v, link, btn) {
    btn.disabled = true;
    post("/api/unlink", { project_id: v.project.id, other_id: link.id }).then(function () {
      toast("Unlinked " + link.name, null, false, false);
      return loadView(v.project.id);
    }).catch(function (err) { btn.disabled = false; fail(err); });
  }

  // "Linked: A x, B x": each name opens that project, its x removes the link.
  function linkedLine(v) {
    if (!v.links || !v.links.length) { return v.linked ? el("span", "m", v.linked) : null; }
    var node = el("span", "m linked", "Linked: ");
    v.links.forEach(function (link, i) {
      var name = el("a", null, link.name);
      name.href = "#/p/" + encodeURIComponent(link.id);
      var x = button("\u00d7", "ghost x", function (b) { unlink(v, link, b); });
      x.title = "Unlink " + link.name;
      x.setAttribute("aria-label", "Unlink " + link.name);
      add(node, i ? document.createTextNode(", ") : null, name, x);
    });
    return node;
  }

  function moreMenu(v) {
    var more = button("\u22ef", "ghost", function () { togglePop("more"); });
    more.title = "More";
    more.setAttribute("aria-label", "More");
    var wrap = add(el("span", "menu"), more);
    if (popOpen !== "more") { return wrap; }
    var pop = el("div", "pop");
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
    return add(wrap, add(pop, button("Rename", null, startRename),
      button("Archive", null, function () { archive(v); }),
      button("Remove project...", null, function () { removeProject(v); })));
  }

  function crumb(v) {
    var node = add(el("div", "crumb"), backButton(v));
    var top = el("a", null, "Projects");
    top.href = "#/";
    node.appendChild(top);
    v.crumbs.forEach(function (c) {
      var link = el("a", null, c.name);
      link.href = "#/p/" + encodeURIComponent(c.id);
      add(node, document.createTextNode(" / "), link);
    });
    return add(node, document.createTextNode(" / " + v.project.name));
  }

  function header(v) {
    var p = v.project;
    var h = add(el("div", "h"), popOpen === "rename" ? nameField(v) : el("h1", null, p.name), linkedLine(v),
      p.archived_at ? el("span", "m", "Archived") : null, el("span", "grow"));
    if (!p.is_inbox && !p.archived_at) { add(h, linkMenu(v), moreMenu(v)); }
    if (p.archived_at) { h.appendChild(button("Unarchive", null, function (b) { unarchive(p.id, p.name, b); })); }
    return h;
  }

  function section(title, count, first) {
    var head = el("h3", null, title);
    if (count !== null) { head.appendChild(el("span", "cnt", count)); }
    return add(el("div", first ? "sec first" : "sec"), head);
  }

  function tile(t) {
    var node = add(el("button", "mini"), el("span", "g " + (TONE[t.status] || "stale"), t.glyph),
      document.createTextNode(t.name), el("span", "sub", t.text));
    node.type = "button";
    node.setAttribute("data-project-id", t.project_id);
    dropTarget(node, t.project_id);
    node.addEventListener("click", function () { window.location.hash = "#/p/" + encodeURIComponent(t.project_id); });
    return node;
  }

  // A run panel: the buttons its `quick` names, then the "..." menu (and right-click) with all its
  // `actions`; it drags onto a sub-project's tile or section to move there. `from`: its project.
  function runPanel(r, from) {
    var tone = TONE[r.status] || "stale";
    var name = el("b", null, r.title);
    name.title = r.title;
    var acts = el("span", "acts");
    quickButtons(r, acts);
    acts.appendChild(menuButton(r));
    var st = add(el("span", "st"), el("span", "w " + tone, r.word), r.detail ? el("span", null, r.detail) : null,
      r.bar.length ? bar(r.bar) : null);
    if (r.started) { add(st, el("span", null, "-"), el("span", null, r.started)); }
    if (r.pr) { add(st, el("span", null, "-"), prLine(r.pr)); }
    var node = add(el("div", r.gone ? "runbig dim" : "runbig"), el("span", "g " + tone, r.glyph), name, acts, st);
    node.setAttribute("data-item-id", r.item_id);
    withMenu(node, r);
    draggable(node, { id: r.item_id, name: r.title, revision: null, from: from });
    return node;
  }

  function sessionRow(s) {
    var title = el("span", "t", s.title);
    title.title = s.title;
    var open = button(ARROW + s.action, s.item_id === hot ? "focus" : null, function (b) { openInTerminal(s.item_id, b); });
    var acts = add(el("span", "acts"), open, button("Copy command", null, function () { copyCommand(s.item_id); }),
      dismissButton(s.item_id));
    var cls = "row" + (s.item_id === hot ? " hot" : "") + (s.gone ? " dim" : "");
    var node = add(el("div", cls), el("span", "g " + (TONE[s.status] || "stale"), s.glyph), el("span", "kind", s.kind),
      title, el("span", "age", s.age), acts);
    node.setAttribute("data-item-id", s.item_id);
    return node;
  }

  // Dismiss hides an item (a run with its attached items) from every list; Restore shows it again;
  // Mark done says a stale run is done. Each is a move: the toast offers Undo, as after a drag.
  function postItemMove(path, itemId, btn) {
    btn.disabled = true;
    post(path, { item_id: itemId }).then(function (r) { moved(r); afterMove(); })
      .catch(function (err) { btn.disabled = false; fail(err); });
  }

  function dismissButton(itemId) {
    var node = button("Dismiss", "ghost", function (b) { postItemMove("/api/dismiss", itemId, b); });
    node.title = "Hide it from every list. Deletes nothing; Restore it from Dismissed.";
    return node;
  }

  // Throw away... is the one action that removes things: the server says what would go (or why
  // not), the dialog lists it, and only an OK sends the confirmed call.
  function throwList(r) {
    var lines = ["Throw away " + r.title + "?", "", "This goes:"];
    lines.push(r.folder ? "- the folder " + r.folder + " (to the Trash)" : "- no folder (it is no longer on this Mac)");
    r.worktrees.forEach(function (t) {
      lines.push("- the worktree " + t.path + " (git worktree remove; the branch " + (t.branch || "-") + " stays)");
      var ignored = t.ignored || [];
      if (ignored.length) {
        lines.push("  git deletes its " + ignored.length + " ignored file" + (ignored.length === 1 ? "" : "s") +
                   " for good, not to the Trash (" + ignored.slice(0, 3).join(", ") + (ignored.length > 3 ? ", ..." : "") + ")");
      }
    });
    lines.push("- the run and its " + r.items + " attached item" + (r.items === 1 ? "" : "s") + ", from the studio");
    lines.push("", "A worktree with changes stops it before the folder moves; ignored files in a worktree do not. There is no Undo; the folder can come back from the Trash.");
    return lines.join("\n");
  }

  function throwAway(itemId, btn) {
    btn.disabled = true;
    post("/api/throw", { item_id: itemId }).then(function (r) {
      if (!window.confirm(throwList(r))) { return null; }
      return post("/api/throw", { item_id: itemId, confirmed: true });
    }).then(function (r) {
      if (r) { toast(r.message, null, false, false); afterMove(); }
    }).catch(fail).then(function () { btn.disabled = false; });
  }

  // ------------------------------------------------------------------ a night run's actions menu

  // What each run action does (sdk/runmenu.py lists which apply): each calls what its button always
  // did. The page draws only the run's `actions`: as the "..." menu, and as buttons for `quick`.
  var RUN_ACTS = {
    "open-plan": function (a, b) { openItem(a.target_id, "plan", b); },
    "open-pr": function (a, b) { openItem(a.target_id, "pr", b); },
    "open-terminal": function (a, b) { openInTerminal(a.target_id, b); },
    "open-conductor": function (a, b) { openInTerminal(a.target_id, b); },
    "move": function (a) { openPicker(a.target_id); },
    "mark-done": function (a, b) { postItemMove("/api/mark-done", a.target_id, b); },
    "dismiss": function (a, b) { postItemMove("/api/dismiss", a.target_id, b); },
    "restore": function (a, b) { postItemMove("/api/restore", a.target_id, b); },
    "throw-away": function (a, b) { throwAway(a.target_id, b); }
  };
  var ACT_LOOK = { "open-terminal": [ARROW, null], "open-conductor": [ARROW, null], dismiss: ["", "ghost"],
    restore: ["", "ghost"], "throw-away": ["", "ghost"] };
  var menuFor = null;     // the run whose actions menu is open

  function quickButtons(run, into) {
    run.actions.forEach(function (a) {
      if (run.quick.indexOf(a.id) < 0 || !RUN_ACTS[a.id]) { return; }
      var look = ACT_LOOK[a.id] || ["", null];
      var node = button(look[0] + a.label, look[1], function (b) { RUN_ACTS[a.id](a, b); });
      node.title = a.hint;
      into.appendChild(node);
    });
  }

  function closeMenu() {
    if (!menuFor) { return; }
    menuFor = null;
    clear($("runmenu"));
    $("runmenu").hidden = true;
  }

  function openMenu(run, x, y, back) {
    closeMenu();
    menuFor = run.item_id;
    var box = $("runmenu");
    var list = el("div", "rmenu");
    list.setAttribute("role", "menu");
    list.setAttribute("aria-label", "Actions for " + run.title);
    list.addEventListener("click", function (e) { e.stopPropagation(); });
    run.actions.forEach(function (a) {
      if (!RUN_ACTS[a.id]) { return; }
      if (a.destructive) { list.appendChild(el("hr")); }
      var item = button(a.label, a.destructive ? "danger" : null, function () {
        closeMenu();
        if (back.focus) { back.focus(); }
        RUN_ACTS[a.id](a, back);
      });
      item.setAttribute("role", "menuitem");
      item.title = a.hint;
      list.appendChild(item);
    });
    list.addEventListener("keydown", function (e) {
      var items = list.querySelectorAll("button");
      var at = Array.prototype.indexOf.call(items, document.activeElement);
      if (e.key === "Escape" || e.key === "Tab") {
        e.preventDefault();
        closeMenu();
        if (back.focus) { back.focus(); }
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        items[(at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
      }
    });
    box.appendChild(list);
    box.hidden = false;
    list.style.left = Math.max(8, Math.min(x, window.innerWidth - list.offsetWidth - 8)) + "px";
    list.style.top = Math.max(8, y + list.offsetHeight + 8 > window.innerHeight ? y - list.offsetHeight : y) + "px";
    var first = list.querySelector("button");
    if (first) { first.focus(); }
  }

  function menuButton(run) {
    var node = button("\u22ef", "ghost more", function (b) {
      if (menuFor === run.item_id) { closeMenu(); return; }
      var at = b.getBoundingClientRect();
      openMenu(run, at.left, at.bottom + 4, b);
    });
    node.title = "Actions (or right-click the run)";
    node.setAttribute("aria-label", "Actions for " + run.title);
    node.setAttribute("aria-haspopup", "menu");
    return node;
  }

  // Right-click on a run line or panel opens the same menu where the pointer is.
  function withMenu(node, run) {
    node.addEventListener("contextmenu", function (e) {
      e.preventDefault();
      e.stopPropagation();
      openMenu(run, e.clientX, e.clientY, node.querySelector(".more") || node);
    });
  }

  function itemRow(r, dismissed) {
    var title = el("span", "t", r.title);
    title.title = r.title;
    if (dismissed) {
      return add(el("div", "row plain"), title, el("span", "age", r.text),
        button(r.action, null, function (b) { postItemMove("/api/restore", r.item_id, b); }));
    }
    return add(el("div", "row plain"), title, el("span", "age", r.text),
      add(el("span", "acts"), button(r.action, null, function (b) { openItem(r.item_id, "default", b); }),
        dismissButton(r.item_id)));
  }

  function fold(v, f) {
    var key = v.project.id + ":" + f.kind;
    var open = !!openFolds[key];
    var head = add(el("button", "fold"), el("span", null, (open ? "\u25be " : "\u25b8 ") + f.label),
      el("span", "cnt", f.count), el("span", null, f.summary));
    head.type = "button";
    head.setAttribute("aria-expanded", open ? "true" : "false");
    head.addEventListener("click", function () { openFolds[key] = !open; renderView(lastView); });
    var frag = add(document.createDocumentFragment(), head);
    if (open) {
      var rows = el("div", "rows");
      if (f.kind === "sessions") {
        v.sessions.forEach(function (s) { rows.appendChild(sessionRow(s)); });
      } else {
        f.rows.forEach(function (r) { rows.appendChild(itemRow(r, f.kind === "dismissed")); });
      }
      frag.appendChild(rows);
    }
    return frag;
  }

  // A section per sub-project under the project's own run panels: header (glyph, name, word,
  // counts in words, Open) and its own run panels, at most `shown` before "+ n more", which
  // expands in place. The SDK says whether it starts open; a click folds or opens it for this
  // page, and a folded section hides the levels under it too.
  var subOpen = {};       // "<project id>:<sub-project id>" -> true / false once toggled
  var subMore = {};       // "<project id>:<sub-project id>" -> true once "+ n more" was clicked

  function subHead(v, g, key, open) {
    var toggle = add(el("button", "subhead"), el("span", "tw", open ? "\u25be" : "\u25b8"),
      el("span", "g " + (TONE[g.status] || "stale"), g.glyph), el("b", null, g.name),
      g.word ? el("span", "w " + (TONE[g.status] || "stale"), g.word) : null, el("span", "sub", g.text));
    toggle.type = "button";
    toggle.title = g.name;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.addEventListener("click", function () { subOpen[key] = !open; renderView(lastView); });
    var go = el("a", "btn", "Open");
    go.href = "#/p/" + encodeURIComponent(g.project_id);
    go.title = "Open " + g.name;
    return add(el("div", "subrow"), toggle, go);
  }

  function subSection(v, g) {
    var key = v.project.id + ":" + g.project_id;
    var open = key in subOpen ? subOpen[key] : g.open;
    var node = add(el("div", "subsec"), subHead(v, g, key, open));
    node.style.marginLeft = ((g.depth - 1) * 20) + "px";
    node.setAttribute("data-project-id", g.project_id);
    dropTarget(node, g.project_id, true);
    if (!open) { return { node: node, open: false }; }
    var all = !!subMore[key];
    var shown = all ? g.runs : g.runs.slice(0, g.shown);
    var body = el("div", "subbody");
    shown.forEach(function (r) { body.appendChild(runPanel(r, g.project_id)); });
    if (!g.runs.length) { body.appendChild(el("p", "none", "No night runs here.")); }
    if (g.more && !all) {
      body.appendChild(button(g.more, "ghost", function () { subMore[key] = true; renderView(lastView); }));
    }
    node.appendChild(body);
    return { node: node, open: true };
  }

  function subSections(v, parent) {
    var foldedAt = 0;     // the depth of the folded section we are under, 0 for none
    v.sub_runs.forEach(function (g) {
      if (foldedAt && g.depth > foldedAt) { return; }
      var made = subSection(v, g);
      foldedAt = made.open ? 0 : g.depth;
      parent.appendChild(made.node);
    });
  }

  function renderView(v) {
    lastView = v;
    var page = $("project");
    clear(page);
    add(page, crumb(v), header(v));
    var first = true;
    function sec(title, count) {
      var node = section(title, count, first);
      first = false;
      page.appendChild(node);
      return node;
    }
    if (v.inside.length) {
      var minis = el("div", "minis");
      v.inside.forEach(function (t) { minis.appendChild(tile(t)); });
      sec("Inside", v.inside.length).appendChild(minis);
    }
    if (v.runs.length || v.sub_runs.length) {
      var total = v.sub_runs.reduce(function (n, g) { return n + g.runs.length; }, v.runs.length);
      var runs = sec("Night runs", total);
      v.runs.forEach(function (r) { runs.appendChild(runPanel(r, v.project.id)); });
      subSections(v, runs);
    }
    if (v.sessions.length && !v.sessions_folded) {
      var rows = el("div", "rows");
      v.sessions.forEach(function (s) { rows.appendChild(sessionRow(s)); });
      sec("Sessions", v.sessions.length).appendChild(rows);
    }
    if (v.folds.length) {
      var rest = sec("Everything else", null);
      v.folds.forEach(function (f) { rest.appendChild(fold(v, f)); });
    }
    if (first && !v.dismissed) { page.appendChild(el("p", "none", "Nothing filed here yet. Move sessions and night runs here from the Inbox.")); }
    var canRule = !v.project.is_inbox && !v.project.archived_at;
    if (v.rules.length || canRule) {
      var list = el("div", "rows");
      v.rules.forEach(function (r) { list.appendChild(ruleRow(v, r)); });
      var rules = sec("Rules", v.rules.length);
      if (canRule) { rules.appendChild(add(el("div", "ruleadd"), ruleForm(v))); }
      rules.appendChild(list);
    }
    if (v.dismissed) { sec("Dismissed", null).appendChild(fold(v, v.dismissed)); }
    document.title = v.project.name + " - Project Studio";
  }

  function viewError(message) {
    var page = $("project");
    clear(page);
    var back = el("a", "btn", "Back to projects");
    back.href = "#/";
    add(page, add(el("div", "empty"), el("p", "lead", message), back));
  }

  function loadView(id) {
    return fetch("/project?id=" + encodeURIComponent(id)).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) { throw new Error(data && data.message ? data.message : "Request failed (" + res.status + ")."); }
        return data;
      });
    }).then(function (v) {
      if (current === id && !popOpen && !frozen()) { renderView(v); }
    }, function (err) {
      if (current === id) { viewError(err.message); }
    });
  }

  function route() {
    current = projectId();
    closeMenu();
    popOpen = null;
    hot = null;
    showDrawer(window.location.hash === "#/inbox");
    $("home").hidden = !!current;
    $("project").hidden = !current;
    if (!current) {
      lastView = null;
      document.title = "Project Studio";
      return;
    }
    if (!lastView || lastView.project.id !== current) {
      lastView = null;
      clear($("project"));
      add($("project"), el("div", "sk w60"), el("p", "none loading", "Reading the project..."));
    }
    loadView(current);
  }

  // ------------------------------------------------------------------ moving: drag, the Inbox drawer, Undo, the picker

  var dragged = null;     // {id, name, revision, from} while a card, a run or an Inbox row is dragged
  var picking = false;    // the "Move to..." / "Set parent" picker is open
  var pending = null;     // the newest home state that arrived while frozen
  var drawerOpen = false;

  function frozen() { return !!dragged || picking; }

  function thaw() {
    if (frozen()) { return; }
    if (pending) { var s = pending; pending = null; render(s); }
    if (drawerOpen) { loadInbox(); }
    if (current) { loadView(current); }
  }

  function afterMove() {
    reload().catch(fail);
    if (drawerOpen) { loadInbox(); }
    if (current) { loadView(current); }
  }

  function ruleText(prefix, parts) {
    var node = el("span", "t", prefix);
    parts.forEach(function (part, i) {
      if (i) { node.appendChild(document.createTextNode(" + ")); }
      add(node, document.createTextNode(part[0] + " "), el("code", null, part[1]));
    });
    return node;
  }

  function ruleOption(r) {
    var saved = null;
    var box = el("input");
    box.type = "checkbox";
    var label = add(el("label"), box, document.createTextNode("Always file items like this here"));
    box.addEventListener("change", function () {
      box.disabled = true;
      var call = box.checked ? post("/api/rule", { move_id: r.move_id }).then(function (rule) { saved = rule; })
        : !saved || !saved.created ? Promise.resolve(saved = null)   // a rule that was there before stays
        : post("/api/rule/delete", { rule_id: saved.id }).then(function () { saved = null; });
      call.catch(function (err) { box.checked = !box.checked; fail(err); }).then(function () {
        box.disabled = false;
        if (current) { loadView(current); }
      });
    });
    return add(el("div", "ib"), label, add(el("div", "s"), ruleText("rule: ", r.rule_preview.parts)));
  }

  function moved(r) {
    var box = $("toasts");
    clear(box);
    var node = add(el("div", "toast"), el("span", null, r.message), el("span", "sp"));
    if (r.move_id !== null) {
      node.appendChild(button("Undo", null, function (undo) {
        undo.disabled = true;
        post("/api/undo", { move_id: r.move_id }).then(function (back) {
          toast(back.message, null, false, false);
          afterMove();
        }).catch(fail);
      }));
    }
    box.appendChild(node);
    if (r.move_id !== null && r.rule_preview) { box.appendChild(ruleOption(r)); }
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(dismiss, 15000);
  }

  function moveTo(target, projectId) {
    return post("/api/move", { target_id: target.id, to_project_id: projectId, revision: target.revision })
      .then(function (r) { moved(r); afterMove(); }).catch(fail);
  }

  function accept(row, btn) {
    btn.disabled = true;
    post("/api/accept", { item_id: row.item_id }).then(function (r) { moved(r); afterMove(); })
      .catch(function (err) { btn.disabled = false; fail(err); });
  }

  // DragGhost: a pill with the dragged name, used as the drag image.
  function ghost(name) {
    var node = $("ghost");
    node.textContent = "\u2630 " + (name.length > 34 ? name.slice(0, 34) + "..." : name);
    return node;
  }

  function draggable(node, what) {
    node.draggable = true;
    node.addEventListener("dragstart", function (e) {
      e.stopPropagation();     // a run line drags alone, not the row around it
      closeMenu();
      dragged = what;
      node.classList.add("drag");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", what.name);
      if (e.dataTransfer.setDragImage) { e.dataTransfer.setDragImage(ghost(what.name), 12, 12); }
    });
    node.addEventListener("dragend", function (e) {
      e.stopPropagation();
      node.classList.remove("drag");
      dragged = null;
      var drops = document.querySelectorAll(".drop");
      for (var i = 0; i < drops.length; i++) { drops[i].classList.remove("drop"); }
      window.setTimeout(thaw, 0);
    });
  }

  // DropTarget: a card, a sub-project block, tile or section takes an Inbox row or a run (move it
  // there) or another card (move under it); not what is dragged, nor a run onto its own project.
  // `inner`: it sits inside another target, and keeps the drop to itself.
  function dropTarget(node, projectId, inner) {
    function ok() { return dragged && dragged.id !== projectId && dragged.from !== projectId; }
    node.addEventListener("dragover", function (e) {
      if (inner && dragged) { e.stopPropagation(); }
      if (!ok()) { return; }
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      node.classList.add("drop");
    });
    node.addEventListener("dragleave", function (e) {
      if (!node.contains(e.relatedTarget)) { node.classList.remove("drop"); }
    });
    node.addEventListener("drop", function (e) {
      if (inner) { e.stopPropagation(); }
      e.preventDefault();
      node.classList.remove("drop");
      if (!ok()) { return; }
      var what = dragged;
      dragged = null;
      moveTo(what, projectId);
    });
  }

  function inboxRow(row) {
    var node = el("div", "ib");
    node.tabIndex = 0;
    node.setAttribute("data-item-id", row.item_id);
    node.title = "Drag onto a card, or press Shift+Cmd+M to move it";
    draggable(node, { id: row.item_id, name: row.title, revision: row.revision });
    var title = el("div", "t", row.title);
    title.title = row.title;
    var line = add(el("div", "s"), el("span", null, row.meta), el("span", "sp"));
    if (row.chip) {
      var chip = el("span", "chip", row.chip);
      chip.title = row.chip_title;
      line.appendChild(chip);
    }
    if (row.can_accept) { line.appendChild(button("Accept", null, function (b) { accept(row, b); })); }
    return add(node, title, line);
  }

  function renderInbox(v) {
    var drawer = $("drawer");
    clear(drawer);
    var close = button("\u2715", "ghost", function () { window.location.hash = "#/"; });
    close.setAttribute("aria-label", "Close the Inbox");
    add(drawer, add(el("h3", null, "Inbox"), el("span", "cnt", v.count), el("span", "sp"), close));
    v.rows.forEach(function (row) { drawer.appendChild(inboxRow(row)); });
    drawer.appendChild(el("p", "none", v.rows.length ? v.hint : v.empty));
  }

  function loadInbox() {
    return fetch("/inbox").then(function (res) { return res.json(); }).then(function (v) {
      if (drawerOpen && !frozen()) { renderInbox(v); }
    }).catch(function () { /* the next state event tries again */ });
  }

  function showDrawer(open) {
    drawerOpen = open;
    $("drawer").hidden = !open;
    $("lay").className = open ? "lay open" : "lay";
    $("inbox").setAttribute("aria-expanded", open ? "true" : "false");
    if (open) { loadInbox(); }
  }

  function ruleRow(v, r) {
    var del = button("Delete", null, function () {
      del.disabled = true;
      post("/api/rule/delete", { rule_id: r.id }).then(function () {
        toast("Rule deleted. Items it filed stay where they are.", null, false, false);
        return loadView(v.project.id);
      }).catch(function (err) { del.disabled = false; fail(err); });
    });
    return add(el("div", "row plain rule"), ruleText("rule: ", r.parts), el("span", "age", ""), del);
  }

  // "Add rule...": a rule by pattern. Check asks for the dry-run count; Save stays off until the
  // count on show is for what the form says now.
  var RULE_SIGNALS = [["workspace", "Workspace", "sis-*"], ["repo-branch", "Repo + branch prefix", "shapes-platform"],
    ["cwd", "Folder", "~/work/shapes"]];

  function ruleForm(v) {
    var wrap = add(el("span", "menu"), button("Add rule...", null, function () { togglePop("rule"); }));
    if (popOpen !== "rule") { return wrap; }
    var pop = el("div", "pop rulepop");
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
    var signal = el("select");
    signal.setAttribute("aria-label", "What the rule matches");
    RULE_SIGNALS.forEach(function (s) {
      var option = el("option", null, s[1]);
      option.value = s[0];
      signal.appendChild(option);
    });
    var pattern = el("input"), branch = el("input"), box = el("input");
    pattern.type = branch.type = "text";
    pattern.setAttribute("aria-label", "Pattern");
    branch.setAttribute("aria-label", "Branch prefix");
    branch.placeholder = "branch prefix, e.g. eval/ (optional)";
    box.type = "checkbox";
    var note = el("div", "note", "Check it first: it says how many Inbox items it would file.");
    var checked = null;     // the {signal, pattern} the count on show is for
    var check = button("Check", null, function () { send(true); });
    var save = button("Save rule", "pri", function () { send(false); });
    function body(dry) {
      var text = pattern.value.trim();
      if (signal.value === "repo-branch" && branch.value.trim()) { text += " " + branch.value.trim(); }
      return { project_id: v.project.id, signal: signal.value, pattern: text, dry_run: dry, apply: !dry && box.checked };
    }
    function sync() {
      var b = body(true);
      pattern.placeholder = RULE_SIGNALS.filter(function (s) { return s[0] === b.signal; })[0][2];
      branch.hidden = b.signal !== "repo-branch";
      save.disabled = !checked || checked.signal !== b.signal || checked.pattern !== b.pattern;
    }
    function send(dry) {
      var b = body(dry);
      check.disabled = save.disabled = true;
      post("/api/rule/add", b).then(function (r) {
        if (dry) {
          checked = b;
          note.className = "note";
          note.textContent = r.message;
          return null;
        }
        popOpen = null;
        ruleSaved(r);
        afterMove();
        return null;
      }).catch(function (err) {
        checked = null;
        note.className = "note err";
        note.textContent = err.message;
      }).then(function () { check.disabled = false; sync(); });
    }
    [signal, pattern, branch].forEach(function (n) {
      n.addEventListener("input", sync);
      n.addEventListener("change", sync);
    });
    sync();
    return add(wrap, add(pop, signal, pattern, branch, note,
      add(el("label"), box, document.createTextNode("Also file the matching Inbox items now")),
      add(el("div", "row2"), button("Cancel", "ghost", closePop), check, save)));
  }

  function ruleSaved(r) {
    var box = $("toasts");
    clear(box);
    var node = add(el("div", "toast"), el("span", null, r.message), el("span", "sp"));
    var ids = r.filed.map(function (f) { return f.move_id; }).filter(function (id) { return id !== null; });
    if (ids.length) {
      node.appendChild(button("Undo filing", null, function (undo) {
        undo.disabled = true;
        ids.reduce(function (done, id) {
          return done.then(function () { return post("/api/undo", { move_id: id }); });
        }, Promise.resolve()).then(function () {
          toast("Moved back to the Inbox. The rule stays.", null, false, false);
          afterMove();
        }).catch(fail);
      }));
    }
    box.appendChild(node);
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(dismiss, 15000);
  }

  // The picker: "Move to..." (Shift+Cmd+M) and "Set parent" (Cmd+Shift+P), the keyboard twins of drag.
  function closePicker(back) {
    picking = false;
    clear($("picker"));
    if (back && back.focus) { back.focus(); }
    thaw();
  }

  function showPicker(c, back) {
    var box = $("picker");
    clear(box);
    var dlg = el("div", "dlg");
    dlg.setAttribute("role", "dialog");
    dlg.setAttribute("aria-modal", "true");
    dlg.setAttribute("aria-label", c.title);
    var head = el("h4", null, c.title);
    head.title = c.title;
    add(dlg, head);
    var scrim = add(el("div", "scrim"), dlg);
    scrim.addEventListener("mousedown", function (e) { if (e.target === scrim) { closePicker(back); } });
    if (!c.choices.length) {
      add(dlg, el("p", null, "There is nowhere else to move it."),
        add(el("div", "acts"), button("Close", null, function () { closePicker(back); })));
      box.appendChild(scrim);
      dlg.querySelector("button").focus();
      return;
    }
    var filter = el("input");
    filter.type = "text";
    filter.placeholder = "Type to filter projects";
    filter.setAttribute("aria-label", "Filter projects");
    var list = el("select");
    list.size = Math.min(8, Math.max(2, c.choices.length));
    list.setAttribute("aria-label", "Projects");
    function fill() {
      var words = filter.value.toLowerCase();
      clear(list);
      c.choices.forEach(function (choice, i) {
        if (words && choice.label.toLowerCase().indexOf(words) < 0) { return; }
        var option = el("option", null, choice.label);
        option.value = String(i);
        list.appendChild(option);
      });
      if (list.options.length) { list.selectedIndex = 0; }
    }
    function go() {
      if (list.selectedIndex < 0) { return; }
      var choice = c.choices[Number(list.value)];
      closePicker(back);
      moveTo({ id: c.target_id, name: c.name, revision: c.revision }, choice.id);
    }
    filter.addEventListener("input", fill);
    dlg.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); closePicker(back); }
      else if (e.key === "Enter" && e.target.tagName !== "BUTTON") { e.preventDefault(); go(); }
      else if (e.target === filter && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        var next = list.selectedIndex + (e.key === "ArrowDown" ? 1 : -1);
        if (next >= 0 && next < list.options.length) { list.selectedIndex = next; }
      }
    });
    list.addEventListener("dblclick", go);
    add(dlg, filter, list, add(el("div", "acts"), button("Cancel", "ghost", function () { closePicker(back); }),
      button(c.kind === "project" ? "Set parent" : "Move", "pri", go)));
    fill();
    box.appendChild(scrim);
    filter.focus();
  }

  function openPicker(targetId) {
    var back = document.activeElement;
    picking = true;
    fetch("/choices?id=" + encodeURIComponent(targetId)).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) { throw new Error(data && data.message ? data.message : "Request failed (" + res.status + ")."); }
        return data;
      });
    }).then(function (c) { showPicker(c, back); }, function (err) { closePicker(back); fail(err); });
  }

  function focused(attr) {
    var node = document.activeElement;
    var holder = node && node.closest ? node.closest("[" + attr + "]") : null;
    return holder ? holder.getAttribute(attr) : null;
  }

  function shortcut(e) {
    if (!(e.metaKey || e.ctrlKey) || !e.shiftKey || picking) { return; }
    var key = (e.key || "").toLowerCase();
    if (key !== "m" && key !== "p") { return; }
    e.preventDefault();
    var project = focused("data-project-id") || current;
    var target = key === "m" ? (focused("data-item-id") || project) : project;
    if (target) { openPicker(target); return; }
    toast(key === "m" ? "Focus an Inbox row, a session or a card (Tab), then press Shift+Cmd+M to move it."
      : "Focus a card (Tab), then press Cmd+Shift+P to set its parent.", null, false, false);
  }

  // ------------------------------------------------------------------ the page

  var showArchived = false;   // the home page's "Show archived" list is open
  var lastState = null;

  // The home rows keep the order they loaded with: a live update changes what a row says, never its
  // place. `pinned` is the SDK's `order` (and which rows were quiet) at load or at the last Re-sort; a
  // project the page has not seen yet (just made) goes first. "Re-sort" shows when the SDK's order
  // differs from the one on the page.
  var pinned = null;          // {at: {project id: place}, quiet: {project id: true}}
  var showQuiet = false;      // the "n quiet projects" fold is open

  function pin(s) {
    pinned = { at: {}, quiet: {} };
    s.order.forEach(function (id, i) { pinned.at[id] = i; });
    s.cards.forEach(function (c) { if (c.quiet) { pinned.quiet[c.project.id] = true; } });
  }

  function place(c) { return c.project.id in pinned.at ? pinned.at[c.project.id] : -1; }
  function foldsQuiet(c) { return c.project.id in pinned.at ? !!pinned.quiet[c.project.id] : c.quiet; }

  function placed(s) {
    var cards = s.cards.slice().sort(function (a, b) { return place(a) - place(b); });
    return { rows: cards.filter(function (c) { return !foldsQuiet(c); }), quiet: cards.filter(foldsQuiet) };
  }

  function reordered(s, shown) {
    var ids = shown.rows.concat(shown.quiet).map(function (c) { return c.project.id; });
    return ids.join(" ") !== s.order.join(" ") || shown.quiet.some(function (c) { return !c.quiet; });
  }

  function resortLink(s, shown) {
    var slot = $("resort");
    clear(slot);
    if (!reordered(s, shown)) { return; }
    var link = button("Re-sort", "ghost", function () { pin(lastState); render(lastState); });
    link.title = "The activity order changed since the page loaded";
    slot.appendChild(link);
  }

  function quietFold(s, rows) {
    var label = rows.length === s.cards.filter(function (c) { return c.quiet; }).length ? s.quiet_text
      : rows.length + (rows.length === 1 ? " quiet project" : " quiet projects");
    var wrap = el("div", "quiet");
    var fold = el("button", "fold", (showQuiet ? "\u25be " : "\u25b8 ") + label);
    fold.type = "button";
    fold.setAttribute("aria-expanded", showQuiet ? "true" : "false");
    fold.addEventListener("click", function () { showQuiet = !showQuiet; render(lastState); });
    wrap.appendChild(fold);
    if (showQuiet) {
      var list = el("div", "prows");
      rows.forEach(function (c) { list.appendChild(card(c)); });
      wrap.appendChild(list);
    }
    return wrap;
  }

  function homeRows(s) {
    if (!pinned) { pin(s); }
    var shown = placed(s);
    resortLink(s, shown);
    var frag = document.createDocumentFragment();
    var list = el("div", "prows");
    shown.rows.forEach(function (c) { list.appendChild(card(c)); });
    frag.appendChild(list);
    if (shown.quiet.length) { frag.appendChild(quietFold(s, shown.quiet)); }
    return frag;
  }

  function archivedList(s) {
    var wrap = el("div", "archived");
    var label = (showArchived ? "Hide archived" : "Show archived") + " (" + s.archived.length + ")";
    wrap.appendChild(button(label, "ghost", function () { showArchived = !showArchived; render(lastState); }));
    if (!showArchived) { return wrap; }
    s.archived.forEach(function (a) {
      var name = el("a", "t", a.name);
      name.href = "#/p/" + encodeURIComponent(a.id);
      wrap.appendChild(add(el("div", "row plain"), name, el("span", "age", "archived " + a.archived_at.slice(0, 10)),
        button("Unarchive", null, function (b) { unarchive(a.id, a.name, b); })));
    });
    return wrap;
  }

  function render(s) {
    lastState = s;
    $("caption").textContent = s.caption;
    $("age").textContent = s.source_age;
    $("inbox-count").textContent = String(s.inbox_count);
    var banners = $("banners");
    clear(banners);
    s.banners.forEach(function (b) { banners.appendChild(banner(b)); });
    if (s.reading_text) { banners.appendChild(el("p", "none reading", s.reading_text)); }
    var body = $("body");
    clear(body);
    if (s.loading) {
      body.appendChild(skeleton());
    } else if (s.first_run) {
      body.appendChild(firstRun(s.first_run_text));
    } else {
      body.appendChild(homeRows(s));
    }
    if (!s.loading && s.archived && s.archived.length) { body.appendChild(archivedList(s)); }
  }

  function live(on) {
    $("live").className = on ? "live" : "live off";
    $("live-text").textContent = on ? "Live" : "Reconnecting...";
  }

  function dark() {
    var theme = root.getAttribute("data-theme");
    if (theme) { return theme === "dark"; }
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function themeLabel() { $("theme").textContent = dark() ? "Light" : "Dark"; }

  function start() {
    $("body").appendChild(skeleton());
    $("new").addEventListener("click", newProject);
    $("inbox").addEventListener("click", openInbox);
    $("theme").addEventListener("click", function () {
      var next = dark() ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store(next);
      themeLabel();
    });
    themeLabel();
    window.addEventListener("hashchange", route);
    document.addEventListener("click", function () { closeMenu(); if (popOpen) { closePop(); } });
    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
    document.addEventListener("keydown", shortcut);
    document.addEventListener("keydown", escapeBack);
    route();
    var events = new EventSource("/events");
    events.addEventListener("state", function (e) {
      live(true);
      var state = JSON.parse(e.data);
      if (frozen()) { pending = state; return; }
      render(state);
      if (drawerOpen) { loadInbox(); }
      if (current) { loadView(current); }
    });
    events.onopen = function () { live(true); };
    events.onerror = function () { live(false); };
  }

  document.addEventListener("DOMContentLoaded", start);
}());
