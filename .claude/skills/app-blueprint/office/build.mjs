// Builds the office site in public/ from the board page (../page.html) and Supreme's logos. Run: node build.mjs
// The page's one inline script moves to board.js, so the site can forbid inline scripts (script-src 'self').
import { readFileSync, writeFileSync, mkdirSync, rmSync, copyFileSync } from "node:fs";

const here = p => new URL(p, import.meta.url);
const page = readFileSync(here("../page.html"), "utf8");
const cut = page.indexOf('<div id="viewport"'), s0 = page.indexOf("<script>"), s1 = page.lastIndexOf("</script>");
if (cut < 0 || s0 < cut || s1 < s0) throw new Error("page.html doesn't have the expected layout");
const head = page.slice(0, cut), body = page.slice(cut, s0), script = page.slice(s0 + "<script>".length, s1);
if (/<script/i.test(head + body)) throw new Error("page.html must have exactly one script");

rmSync(here("./public/"), { recursive: true, force: true }); // only build output lives here: start clean so nothing stale ships
mkdirSync(here("./public/"), { recursive: true });
const logos = ["icon.png", "logo.png", "logo-white.png"]; // the staff hub's own Supreme brand files
logos.forEach(f => copyFileSync(here("../../../../hub/static/hub/brand/supreme/" + f), here("./public/" + f)));
writeFileSync(here("./public/board.js"), script);
writeFileSync(here("./public/index.html"),
  '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">' +
  '<meta name="robots" content="noindex,nofollow"><link rel="icon" href="icon.png" type="image/png">' +
  "<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}" +
  "body{margin:0;font:14px system-ui}img{max-width:100%}[hidden]{display:none!important}</style>" +
  head + "</head><body>" + body + '<script src="board.js" defer></script></body></html>\n');
console.log(`public/ built: index.html, board.js, ${logos.join(", ")}`);
