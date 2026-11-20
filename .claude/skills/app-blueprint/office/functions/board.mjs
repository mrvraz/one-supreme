// The office board's only server code: GET /api/board reads the whole board, POST applies up to 50 writes.
// Everything needs the passcode (BOARD_KEY, set by Vince in Netlify); the data lives in Netlify Blobs.
import { createHash, timingSafeEqual } from "node:crypto";
import seed from "../seed/board.json" with { type: "json" };

const COLS = new Set(["checks", "custom", "plan", "log", "meta"]);
const ID = /^[A-Za-z0-9_\-.~:@+]{1,120}$/;
const KEY = /^[A-Za-z0-9_]{1,40}$/;
const RESERVED = new Set(["__proto__", "constructor", "prototype"]);
const STATUS = new Set(["todo", "doing", "done", "na"]);
const MAX_WRITES = 50, MAX_DOC = 8 * 1024, MAX_BOARD = 2 * 1024 * 1024;

const json = (body, status = 200, extra = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store", ...extra } });
const sha = s => createHash("sha256").update(String(s)).digest();
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fresh = () => ({ rev: 1, checks: {}, custom: {}, plan: {}, log: {}, meta: {}, ...structuredClone(seed) });

// Text, numbers, true/false, and lists or small objects of those: nothing a page could run.
function plain(v, depth) {
  if (depth > 4) return false;
  if (v === null || typeof v === "string" || typeof v === "boolean") return true;
  if (typeof v === "number") return Number.isFinite(v);
  if (Array.isArray(v)) return v.length <= 50 && v.every(x => plain(x, depth + 1));
  if (typeof v === "object") return Object.keys(v).length <= 30 && Object.entries(v).every(([k, x]) => KEY.test(k) && !RESERVED.has(k) && plain(x, depth + 1));
  return false;
}
function problem(w) {
  if (!w || typeof w !== "object") return "Each write must be an object.";
  if (!["set", "merge", "delete"].includes(w.op)) return "op must be set, merge or delete.";
  if (!COLS.has(w.col)) return "col must be checks, custom, plan, log or meta.";
  if (typeof w.id !== "string" || !ID.test(w.id) || RESERVED.has(w.id)) return "id must be 1 to 120 letters, digits or _ - . ~ : @ +.";
  if (w.op === "delete") return null;
  if (!w.data || typeof w.data !== "object" || Array.isArray(w.data)) return "data must be an object.";
  if (JSON.stringify(w.data).length > MAX_DOC) return "A document is over 8 KB.";
  if (!plain(w.data, 0)) return "data may hold only text, numbers, true/false and lists.";
  if ("status" in w.data && !STATUS.has(w.data.status)) return "status must be todo, doing, done or na.";
  return null;
}
function apply(board, writes) {
  for (const w of writes) {
    const col = board[w.col] && typeof board[w.col] === "object" ? board[w.col] : (board[w.col] = {});
    if (w.op === "delete") delete col[w.id];
    else if (w.op === "set") col[w.id] = w.data;
    else col[w.id] = { ...(col[w.id] || {}), ...w.data };
  }
  return board;
}
// null: no usable passcode is set up; otherwise whether the request carries it (compared in constant time)
function allowed(req, env) {
  const want = String(env.BOARD_KEY || "");
  if (want.length < 12) return null;
  return timingSafeEqual(sha(want), sha(req.headers.get("x-board-key") || ""));
}

export async function handle(req, store, env) {
  const ok = allowed(req, env);
  if (ok === null) return json({ error: "The board's passcode isn't set up yet (BOARD_KEY, 12+ characters)." }, 503);
  if (!ok) { await sleep(800); return json({ error: "Wrong passcode." }, 401); } // slows guessing
  if (req.method === "GET") {
    const cur = (await store.get("board", { type: "json" })) || fresh();
    const tag = `"${cur.rev}"`;
    if (req.headers.get("if-none-match") === tag) return new Response(null, { status: 304, headers: { etag: tag, "cache-control": "no-store" } });
    return json(cur, 200, { etag: tag });
  }
  if (req.method !== "POST") return json({ error: "Use GET or POST." }, 405);
  let body;
  try { body = await req.json(); } catch { return json({ error: "The body isn't JSON." }, 400); }
  const writes = Array.isArray(body && body.writes) ? body.writes : null;
  if (!writes || !writes.length || writes.length > MAX_WRITES) return json({ error: `Send 1 to ${MAX_WRITES} writes.` }, 400);
  for (const w of writes) { const p = problem(w); if (p) return json({ error: p }, 400); }
  for (let attempt = 0; attempt < 6; attempt++) {
    const got = await store.getWithMetadata("board", { type: "json" });
    const cur = got && got.data && typeof got.data === "object" ? got.data : fresh();
    const next = apply(structuredClone(cur), writes);
    next.rev = (Number(cur.rev) || 0) + 1;
    if (JSON.stringify(next).length > MAX_BOARD) return json({ error: "The board is full: delete old log entries." }, 413);
    const res = got ? await store.setJSON("board", next, { onlyIfMatch: got.etag }) : await store.setJSON("board", next, { onlyIfNew: true });
    if (res.modified) return json(next, 200, { etag: `"${next.rev}"` });
    await sleep(40 + Math.random() * 120); // someone else saved first: read again and reapply
  }
  return json({ error: "The board is busy. Try again." }, 409);
}

export default async req => {
  const { getStore } = await import("@netlify/blobs");
  return handle(req, getStore({ name: "blueprint", consistency: "strong" }), process.env);
};
export const config = { path: "/api/board" };
