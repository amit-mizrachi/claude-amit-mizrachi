// Walks a list of browser steps on an app (a cloud box link or a local stack), records ONE video of the
// whole walk and a screenshot per "shot" step, and writes gallery.html: the page the tester publishes
// as an Artifact. Run it through box-capture.sh, which installs Playwright and loads the Access token.
//
//   node box-capture.mjs <base-url> <out-dir> <steps.json>
//
// steps.json is a JSON array of steps, each an array like the box browser's steps:
//   ["login", "admin"]            sign in as <role>@shapes.co (super-admin|admin|manager|employee)
//   ["open", "/people"]           go to an app path
//   ["click", "text=Save"]        click a Playwright selector
//   ["fill", "#name", "Ada"]      fill a field
//   ["press", "Enter"]            press a key
//   ["wait", "1500" | selector]   wait some ms, or for a selector to be visible
//   ["scroll", "600"]             scroll down by px
//   ["shot", "people list", "what the step proves"]   a screenshot with a caption
// A failing step takes error-<n>.png and ends the walk; the video and gallery are still written.
import { chromium } from "playwright";
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const [base, out, stepsFile] = process.argv.slice(2);
if (!base || !out || !stepsFile) {
  console.error("usage: node box-capture.mjs <base-url> <out-dir> <steps.json>");
  process.exit(2);
}
const steps = JSON.parse(readFileSync(stepsFile, "utf8"));
const origin = new URL(base).origin;
const host = new URL(base).host;
const VIEWPORT = { width: 1280, height: 800 };
const STEP_TIMEOUT_MS = 30_000;
const NAV_TIMEOUT_MS = 90_000;
mkdirSync(join(out, "shots"), { recursive: true });
mkdirSync(join(out, "video-raw"), { recursive: true });

const accessId = process.env.BOX_ACCESS_CLIENT_ID;
const accessSecret = process.env.BOX_ACCESS_CLIENT_SECRET;
const password = process.env.BOX_LOGIN_PASSWORD;

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT,
  recordVideo: { dir: join(out, "video-raw"), size: VIEWPORT },
});
// The Access headers go only to the box host, never to any other origin the page loads.
if (accessId && accessSecret)
  await context.route("**/*", (route) => {
    const request = route.request();
    if (new URL(request.url()).host !== host) return route.continue();
    return route.continue({
      headers: {
        ...request.headers(),
        "cf-access-client-id": accessId,
        "cf-access-client-secret": accessSecret,
      },
    });
  });
const page = await context.newPage();
page.setDefaultTimeout(STEP_TIMEOUT_MS);
page.setDefaultNavigationTimeout(NAV_TIMEOUT_MS);
const consoleErrors = [];
page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 300)));

const log = [];
const shots = [];
const settle = async () => {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
};

async function run(step, n) {
  const [kind, a, b] = step;
  switch (kind) {
    case "login": {
      if (!/^(super-admin|admin|manager|employee)$/.test(a ?? "")) throw new Error(`login takes a role, got ${a}`);
      if (!password) throw new Error("BOX_LOGIN_PASSWORD is not set");
      await page.goto(`${origin}/login`);
      await page.locator('input[placeholder="Enter your email"]').fill(`${a}@shapes.co`);
      const pw = page.locator('input[placeholder="Enter your password"]');
      if (!(await pw.isVisible().catch(() => false))) await page.keyboard.press("Enter");
      await pw.fill(password);
      await pw.press("Enter");
      await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: NAV_TIMEOUT_MS });
      return settle();
    }
    case "open":
      await page.goto(new URL(a, origin).toString());
      return settle();
    case "click":
      await page.locator(a).first().click();
      return settle();
    case "fill":
      return page.locator(a).first().fill(b ?? "");
    case "press":
      await page.keyboard.press(a);
      return settle();
    case "wait":
      if (/^\d+$/.test(a)) return page.waitForTimeout(Number(a));
      return page.locator(a).first().waitFor({ state: "visible" });
    case "scroll":
      await page.mouse.wheel(0, Number(a ?? 500));
      return page.waitForTimeout(400);
    case "shot": {
      const file = `shots/${String(n).padStart(2, "0")}-${(a ?? "shot").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.png`;
      await settle();
      await page.screenshot({ path: join(out, file) });
      shots.push({ file, title: a ?? `step ${n}`, note: b ?? "" });
      return;
    }
    default:
      throw new Error(`unknown step ${kind}`);
  }
}

let failed;
for (const [i, step] of steps.entries()) {
  const n = i + 1;
  const started = Date.now();
  try {
    await run(step, n);
    log.push({ n, step, result: "PASS", ms: Date.now() - started, url: page.url() });
    console.log(`PASS ${n} ${JSON.stringify(step)}`);
  } catch (error) {
    const file = `shots/error-${String(n).padStart(2, "0")}.png`;
    await page.screenshot({ path: join(out, file) }).catch(() => {});
    shots.push({ file, title: `FAILED at step ${n}`, note: `${JSON.stringify(step)}: ${String(error.message).split("\n")[0]}` });
    log.push({ n, step, result: "FAIL", error: String(error.message).slice(0, 500), url: page.url() });
    console.log(`FAIL ${n} ${JSON.stringify(step)} ${String(error.message).split("\n")[0]}`);
    failed = n;
    break;
  }
}
await page.waitForTimeout(1000);
await context.close();
await browser.close();

// One webm per page; keep the walk as video/walk.webm, plus an mp4 when ffmpeg is here (Safari plays mp4 only).
mkdirSync(join(out, "video"), { recursive: true });
const raw = readdirSync(join(out, "video-raw")).filter((f) => f.endsWith(".webm"));
let video;
if (raw[0]) {
  renameSync(join(out, "video-raw", raw[0]), join(out, "video", "walk.webm"));
  video = "video/walk.webm";
  const mp4 = spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-i", join(out, "video", "walk.webm"),
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "28", join(out, "video", "walk.mp4")]);
  if (mp4.status === 0 && existsSync(join(out, "video", "walk.mp4"))) video = "video/walk.mp4";
}

writeFileSync(join(out, "steps.json"), JSON.stringify({ base, failed: failed ?? null, consoleErrors, log, shots, video }, null, 2));
writeFileSync(join(out, "gallery.html"), gallery());
console.log(`${failed ? "FAIL" : "PASS"} ${log.filter((l) => l.result === "PASS").length}/${steps.length} steps; video=${video ?? "none"}; shots=${shots.length}; out=${out}`);
process.exit(failed ? 1 : 0);

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function gallery() {
  const title = process.env.BOX_CAPTURE_TITLE || "Sprint test walk";
  const verdict = failed ? `FAIL at step ${failed}` : `PASS, ${log.length} steps`;
  const rows = log
    .map((l) => `<tr><td>${l.n}</td><td><code>${esc(JSON.stringify(l.step))}</code></td><td class="${l.result}">${l.result}</td><td>${esc(l.error ?? "")}</td></tr>`)
    .join("\n");
  const figs = shots
    .map((s) => `<figure><img src="${esc(s.file)}" alt="${esc(s.title)}" loading="lazy"><figcaption><strong>${esc(s.title)}</strong>${s.note ? ` - ${esc(s.note)}` : ""}</figcaption></figure>`)
    .join("\n");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#57534e;--line:#e7e5e4;--card:#fff;--pass:#15803d;--fail:#b91c1c}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--line:#44403c;--card:#292524;--pass:#4ade80;--fail:#f87171}}
:root[data-theme="dark"]{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--line:#44403c;--card:#292524;--pass:#4ade80;--fail:#f87171}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{margin:0 0 4px;font-size:24px}
.meta{color:var(--muted);margin:0 0 24px}.verdict{font-weight:600;color:${failed ? "var(--fail)" : "var(--pass)"}}
video,img{width:100%;height:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
figure{margin:0 0 28px}figcaption{color:var(--muted);margin-top:6px}
table{width:100%;border-collapse:collapse;margin:16px 0 32px;font-size:13px;display:block;overflow-x:auto}
td{border-bottom:1px solid var(--line);padding:6px 8px;vertical-align:top}code{word-break:break-all}
.PASS{color:var(--pass);font-weight:600}.FAIL{color:var(--fail);font-weight:600}h2{font-size:18px;margin:28px 0 10px}
</style></head><body><main>
<h1>${esc(title)}</h1>
<p class="meta"><span class="verdict">${esc(verdict)}</span> &middot; ${esc(base)} &middot; ${esc(new Date().toISOString().slice(0, 16).replace("T", " "))} UTC</p>
${video ? `<h2>Video of the whole walk</h2><video src="${esc(video)}" controls muted playsinline preload="metadata"></video>` : ""}
<h2>Screenshots</h2>
${figs || "<p>No screenshots.</p>"}
<h2>Steps</h2>
<table><tbody>${rows}</tbody></table>
${consoleErrors.length ? `<h2>Page errors</h2><pre>${esc(consoleErrors.join("\n"))}</pre>` : ""}
</main></body></html>
`;
}
