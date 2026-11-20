// ONE SUPREME's way to read and tick the office board. The passcode comes from the ONE_SUPREME_BOARD_KEY environment
// variable, which Vince sets himself on this computer; this script never prints it.
//   node cli.mjs pull board.json     saves the whole board to board.json
//   node cli.mjs push writes.json    sends {"writes":[{"op":"merge","col":"checks","id":"05-...","data":{...}}]}
import { readFileSync, writeFileSync } from "node:fs";

const BASE = (process.env.ONE_SUPREME_BOARD_URL || "https://one-supreme-blueprint.netlify.app").replace(/\/+$/, "");
const KEY = process.env.ONE_SUPREME_BOARD_KEY || "";
const [cmd, file] = process.argv.slice(2);
const fail = (msg, code = 1) => { console.error(msg); process.exit(code); };
if (!["pull", "push"].includes(cmd) || !file) fail("Usage: node cli.mjs pull <board.json> | push <writes.json>", 2);
if (!KEY) fail("ONE_SUPREME_BOARD_KEY isn't set on this computer. Vince sets it once (see SKILL.md).", 2);

const call = (method, body) => fetch(BASE + "/api/board", {
  method, headers: { "x-board-key": KEY, "content-type": "application/json" }, body: body && JSON.stringify(body)
});
const why = async r => { try { return (await r.json()).error || r.statusText; } catch { return r.statusText; } };

if (cmd === "pull") {
  const r = await call("GET");
  if (!r.ok) fail(`Couldn't read the board (${r.status}): ${await why(r)}`);
  const b = await r.json();
  writeFileSync(file, JSON.stringify(b, null, 1));
  const n = o => Object.keys(o || {}).length;
  console.log(`Saved the board (version ${b.rev}) to ${file}: ${n(b.checks)} checks, ${n(b.custom)} One Supreme checks, ${n(b.plan)} plan items, ${n(b.log)} log entries.`);
} else {
  const raw = JSON.parse(readFileSync(file, "utf8"));
  const writes = Array.isArray(raw) ? raw : raw && raw.writes;
  if (!Array.isArray(writes) || !writes.length) fail(`${file} has no writes.`);
  let rev = 0;
  for (let i = 0; i < writes.length; i += 50) {
    const r = await call("POST", { writes: writes.slice(i, i + 50) });
    if (!r.ok) fail(`Stopped after ${i} of ${writes.length} writes (${r.status}): ${await why(r)}`);
    rev = (await r.json()).rev;
  }
  console.log(`Saved ${writes.length} writes. The board is at version ${rev}.`);
}
