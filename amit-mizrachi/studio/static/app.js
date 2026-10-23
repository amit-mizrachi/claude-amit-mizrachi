/* Project Studio - the page script. It only draws what the server sends: the HomeState (GET /state
   and the `state` events of GET /events) and, at #/p/<id>, the ProjectView (GET /project?id=, read
   again on every `state` event). The order, the texts and every status word come from the SDK
   (studio/sdk/home.py, studio/sdk/projectview.py); an action POSTs an item id, never a URL, path or
   command. No ranking, sorting or status rule lives here. All text goes in through textContent,
   never as HTML. */
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
    return fetch("/state").then(function (res) { return res.json(); }).then(render);
  }

  function newProject() {
    var name = window.prompt("Project name");
    if (name === null) { return; }
    post("/api/projects", { name: name }).then(reload).catch(function (err) { window.alert(err.message); });
  }

  function openInbox() { window.location.hash = "#/inbox"; }

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
      reload();
      return loadView(v.project.id);
    }).catch(fail);
  }

  function archive(v) {
    closePop();
    if (!window.confirm("Archive " + v.project.name + "? It and everything under it leave the lists. Nothing is deleted.")) { return; }
    post("/api/archive", { project_id: v.project.id }).then(function () {
      window.location.hash = "#/";
      reload();
      toast("Archived " + v.project.name, null, false, false);
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
    return add(el("div", r.gone ? "runbig dim" : "runbig"), el("span", "g " + tone, r.glyph), name, acts, st);
  }

  function sessionRow(s) {
    var title = el("span", "t", s.title);
    title.title = s.title;
    var open = button(ARROW + s.action, s.item_id === hot ? "focus" : null, function (b) { openInTerminal(s.item_id, b); });
    var acts = add(el("span", "acts"), open, button("Copy command", null, function () { copyCommand(s.item_id); }));
    var cls = "row" + (s.item_id === hot ? " hot" : "") + (s.gone ? " dim" : "");
    return add(el("div", cls), el("span", "g " + (TONE[s.status] || "stale"), s.glyph), el("span", "kind", s.kind),
      title, el("span", "age", s.age), acts);
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
      if (current === id && !popOpen) { renderView(v); }
    }, function (err) {
      if (current === id) { viewError(err.message); }
    });
  }

  function route() {
    current = projectId();
    popOpen = null;
    hot = null;
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

  // ------------------------------------------------------------------ the page

  function render(s) {
    $("caption").textContent = s.caption;
    $("age").textContent = s.source_age;
    $("inbox-count").textContent = String(s.inbox_count);
    var banners = $("banners");
    clear(banners);
    s.banners.forEach(function (b) { banners.appendChild(banner(b)); });
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
    route();
    var events = new EventSource("/events");
    events.addEventListener("state", function (e) {
      live(true);
      render(JSON.parse(e.data));
      if (current) { loadView(current); }
    });
    events.onopen = function () { live(true); };
    events.onerror = function () { live(false); };
  }

  document.addEventListener("DOMContentLoaded", start);
}());
