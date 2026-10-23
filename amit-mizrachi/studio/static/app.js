/* Project Studio - the home page script. It only draws the HomeState the server sends (GET /state
   and the `state` events of GET /events): the order, the run lines, the texts and every status
   word come from the SDK (studio/sdk/home.py). No ranking, sorting or status rule lives here.
   All text goes in through textContent, never as HTML. */
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
    var events = new EventSource("/events");
    events.addEventListener("state", function (e) { live(true); render(JSON.parse(e.data)); });
    events.onopen = function () { live(true); };
    events.onerror = function () { live(false); };
  }

  document.addEventListener("DOMContentLoaded", start);
}());
