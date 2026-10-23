/* Project Studio - the page script. It only draws what the server sends: the HomeState (GET /state
   and the `state` events of GET /events), at #/p/<id> the ProjectView (GET /project?id=, read
   again on every `state` event), at #/inbox the Inbox drawer (GET /inbox) beside the cards, and the
   "Move to..." / "Set parent" picker (GET /choices?id=). The order, the texts and every status word
   come from the SDK (studio/sdk/home.py, projectview.py, inboxview.py); an action POSTs ids, never
   a URL, path or command. No ranking, sorting or status rule lives here. All text goes in through
   textContent, never as HTML. Live re-ordering waits while a drag or the picker is open. */
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
  var TONE = { "needs-you": "wait", blocked: "blk", running: "run_", done: "done", pending: "pend", paused: "pend", unknown: "stale" };
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

  function runLine(run) {
    var tone = TONE[run.status] || "stale";
    var line = el("div", run.gone ? "run dim" : "run");
    var name = el("span", "nm", run.title);
    name.title = run.title;
    add(line, el("span", "g " + tone, run.glyph), name);
    if (run.open_plan_url) {
      var plan = el("a", "btn pri", "Open plan");
      plan.href = run.open_plan_url;
      plan.target = "_blank";
      plan.rel = "noopener noreferrer";
      plan.addEventListener("click", function (e) { e.stopPropagation(); });
      line.appendChild(plan);
    }
    var st = add(el("span", "st"), el("span", "w " + tone, run.word));
    if (run.reason) { st.appendChild(el("span", null, run.reason)); }
    if (run.progress) { st.appendChild(el("span", null, run.progress)); }
    if (run.bar && run.bar.length) { st.appendChild(bar(run.bar)); }
    return add(line, st);
  }

  function card(c) {
    var node = el("div", "card" + (ATTENTION[c.attention] ? " " + ATTENTION[c.attention] : ""));
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
    add(node, add(el("div", "ct"), title, c.inside ? el("span", "sub", c.inside) : null));
    c.runs.forEach(function (run) { node.appendChild(runLine(run)); });
    if (c.empty) { node.appendChild(el("span", "none", c.empty)); }
    if (c.more) { node.appendChild(el("span", "more", c.more)); }
    if (c.pr) { node.appendChild(prLine(c.pr)); }
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
    var grid = el("div", "grid");
    for (var i = 0; i < 4; i++) {
      grid.appendChild(add(el("div", "card"), el("div", "sk w60"), el("div", "sk w90"), el("div", "sk w40")));
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
  var popOpen = null;     // "link" or "more" while a header menu is open
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

  function rename(v) {
    closePop();
    var name = window.prompt("Rename project", v.project.name);
    if (name === null) { return; }
    post("/api/rename", { project_id: v.project.id, name: name }).then(function () {
      return reload().then(function () { return loadView(v.project.id); });
    }).catch(fail);
  }

  function archive(v) {
    closePop();
    if (!window.confirm("Archive " + v.project.name + "? It and everything under it leave the lists. Nothing is deleted.")) { return; }
    post("/api/archive", { project_id: v.project.id }).then(function () {
      window.location.hash = "#/";
      return reload().then(function () { toast("Archived " + v.project.name, null, false, false); });
    }).catch(fail);
  }

  function moreMenu(v) {
    var more = button("\u22ef", "ghost", function () { togglePop("more"); });
    more.title = "More";
    more.setAttribute("aria-label", "More");
    var wrap = add(el("span", "menu"), more);
    if (popOpen !== "more") { return wrap; }
    var pop = el("div", "pop");
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
    return add(wrap, add(pop, button("Rename...", null, function () { rename(v); }),
      button("Archive", null, function () { archive(v); })));
  }

  function crumb(v) {
    var node = el("div", "crumb");
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
    var h = add(el("div", "h"), el("h1", null, p.name), v.linked ? el("span", "m", v.linked) : null,
      p.archived_at ? el("span", "m", "Archived") : null, el("span", "grow"));
    if (!p.is_inbox && !p.archived_at) { add(h, linkMenu(v), moreMenu(v)); }
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
    node.addEventListener("click", function () { window.location.hash = "#/p/" + encodeURIComponent(t.project_id); });
    return node;
  }

  function runPanel(r) {
    var tone = TONE[r.status] || "stale";
    var name = el("b", null, r.title);
    name.title = r.title;
    var acts = el("span", "acts");
    if (r.has_plan) { acts.appendChild(button("Open plan", null, function (b) { openItem(r.item_id, "plan", b); })); }
    if (r.has_pr) { acts.appendChild(button("Open PR", null, function (b) { openItem(r.item_id, "pr", b); })); }
    if (r.terminal_item_id) {
      acts.appendChild(button(ARROW + "Open in Terminal", null, function (b) { openInTerminal(r.terminal_item_id, b); }));
    }
    var st = add(el("span", "st"), el("span", "w " + tone, r.word), r.detail ? el("span", null, r.detail) : null,
      r.bar.length ? bar(r.bar) : null);
    if (r.started) { add(st, el("span", null, "-"), el("span", null, r.started)); }
    if (r.pr) { add(st, el("span", null, "-"), prLine(r.pr)); }
    var node = add(el("div", r.gone ? "runbig dim" : "runbig"), el("span", "g " + tone, r.glyph), name, acts, st);
    node.setAttribute("data-item-id", r.item_id);
    return node;
  }

  function sessionRow(s) {
    var title = el("span", "t", s.title);
    title.title = s.title;
    var open = button(ARROW + s.action, s.item_id === hot ? "focus" : null, function (b) { openInTerminal(s.item_id, b); });
    var acts = add(el("span", "acts"), open, button("Copy command", null, function () { copyCommand(s.item_id); }));
    var cls = "row" + (s.item_id === hot ? " hot" : "") + (s.gone ? " dim" : "");
    var node = add(el("div", cls), el("span", "g " + (TONE[s.status] || "stale"), s.glyph), el("span", "kind", s.kind),
      title, el("span", "age", s.age), acts);
    node.setAttribute("data-item-id", s.item_id);
    return node;
  }

  function itemRow(r) {
    var title = el("span", "t", r.title);
    title.title = r.title;
    return add(el("div", "row plain"), title, el("span", "age", r.text),
      button(r.action, null, function (b) { openItem(r.item_id, "default", b); }));
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
        f.rows.forEach(function (r) { rows.appendChild(itemRow(r)); });
      }
      frag.appendChild(rows);
    }
    return frag;
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
    if (v.runs.length) {
      var runs = sec("Night runs", v.runs.length);
      v.runs.forEach(function (r) { runs.appendChild(runPanel(r)); });
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
    if (v.rules.length) {
      var list = el("div", "rows");
      v.rules.forEach(function (r) { list.appendChild(ruleRow(v, r)); });
      sec("Rules", v.rules.length).appendChild(list);
    }
    if (first) { page.appendChild(el("p", "none", "Nothing filed here yet. Move sessions and night runs here from the Inbox.")); }
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

  var dragged = null;     // {id, name, revision} while a card or an Inbox row is dragged
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
      dragged = what;
      node.classList.add("drag");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", what.name);
      if (e.dataTransfer.setDragImage) { e.dataTransfer.setDragImage(ghost(what.name), 12, 12); }
    });
    node.addEventListener("dragend", function () {
      node.classList.remove("drag");
      dragged = null;
      var drops = document.querySelectorAll(".card.drop");
      for (var i = 0; i < drops.length; i++) { drops[i].classList.remove("drop"); }
      window.setTimeout(thaw, 0);
    });
  }

  // DropTarget: a card takes an Inbox row (file it there) or another card (move under it).
  function dropTarget(node, projectId) {
    function ok() { return dragged && dragged.id !== projectId; }
    node.addEventListener("dragover", function (e) {
      if (!ok()) { return; }
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      node.classList.add("drop");
    });
    node.addEventListener("dragleave", function (e) {
      if (!node.contains(e.relatedTarget)) { node.classList.remove("drop"); }
    });
    node.addEventListener("drop", function (e) {
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

  function render(s) {
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
      var grid = el("div", "grid");
      s.cards.forEach(function (c) { grid.appendChild(card(c)); });
      body.appendChild(grid);
    }
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
    document.addEventListener("click", function () { if (popOpen) { closePop(); } });
    document.addEventListener("keydown", shortcut);
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
