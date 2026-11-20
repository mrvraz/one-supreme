// Self-check for functions/board.mjs with an in-memory stand-in for Netlify Blobs. Run: node test.mjs
import assert from "node:assert/strict";
import { handle } from "./functions/board.mjs";
import seed from "./seed/board.json" with { type: "json" };

function memStore() {
  let rec = null, n = 0, race = false;
  return {
    async get() { return rec ? structuredClone(rec.data) : null; },
    async getWithMetadata() { return rec ? { data: structuredClone(rec.data), etag: rec.etag, metadata: {} } : null; },
    async setJSON(k, data, o = {}) {
      if (race && rec) { // another writer saves first: their change lands, ours must be retried on top
        race = false;
        rec = { data: { ...rec.data, rev: rec.data.rev + 1, plan: { ...rec.data.plan, other: { title: "Saved by someone else" } } }, etag: "e" + (++n) };
        return { modified: false };
      }
      if (o.onlyIfNew && rec) return { modified: false };
      if (o.onlyIfMatch && (!rec || rec.etag !== o.onlyIfMatch)) return { modified: false };
      rec = { data: structuredClone(data), etag: "e" + (++n) };
      return { modified: true, etag: rec.etag };
    },
    raceNext() { race = true; }
  };
}
const KEY = "made-up-test-passcode";
const env = { BOARD_KEY: KEY };
const req = (method, body, key = KEY, headers = {}) => new Request("https://board.test/api/board", {
  method, headers: { "x-board-key": key, "content-type": "application/json", ...headers },
  body: body == null ? undefined : typeof body === "string" ? body : JSON.stringify(body)
});
const post = (s, writes) => handle(req("POST", { writes }), s, env);
const ID = "05-set-retention-periods";

// passcode
assert.equal((await handle(req("GET"), memStore(), {})).status, 503, "no BOARD_KEY: not set up");
assert.equal((await handle(req("GET"), memStore(), { BOARD_KEY: "too-short" })).status, 503, "short BOARD_KEY refused");
assert.equal((await handle(req("GET", null, "wrong-passcode-123"), memStore(), env)).status, 401, "wrong passcode");
assert.equal((await handle(req("GET", null, ""), memStore(), env)).status, 401, "missing passcode");

// first read starts from ONE SUPREME's data; an unchanged board answers 304
const s = memStore();
let r = await handle(req("GET"), s, env);
assert.equal(r.status, 200);
let b = await r.json();
assert.equal(Object.keys(b.checks).length, Object.keys(seed.checks).length);
assert.equal((await handle(req("GET", null, KEY, { "if-none-match": r.headers.get("etag") }), s, env)).status, 304);

// a tick merges into ONE SUPREME's document and keeps its note
r = await post(s, [{ op: "merge", col: "checks", id: ID, data: { status: "doing", by: "Board" } }]);
assert.equal(r.status, 200);
b = await r.json();
assert.equal(b.checks[ID].status, "doing");
assert.equal(b.checks[ID].note, seed.checks[ID].note, "merge kept the note");
assert.equal(b.rev, seed.rev + 1);

// set replaces, delete removes
b = await (await post(s, [{ op: "set", col: "plan", id: "t1", data: { title: "Test plan item", state: "next" } }])).json();
assert.deepEqual(b.plan.t1, { title: "Test plan item", state: "next" });
b = await (await post(s, [{ op: "delete", col: "plan", id: "t1" }])).json();
assert.equal(b.plan.t1, undefined);

// two writers at once: both changes survive
s.raceNext();
r = await post(s, [{ op: "merge", col: "checks", id: ID, data: { status: "done" } }]);
assert.equal(r.status, 200);
b = await r.json();
assert.equal(b.checks[ID].status, "done");
assert.equal(b.plan.other.title, "Saved by someone else");

// anything malformed is refused before it's stored
const bad = [
  { writes: [] },
  { writes: Array.from({ length: 51 }, (_, i) => ({ op: "delete", col: "log", id: "x" + i })) },
  { writes: [{ op: "drop", col: "checks", id: "a", data: {} }] },
  { writes: [{ op: "set", col: "secrets", id: "a", data: {} }] },
  { writes: [{ op: "set", col: "checks", id: "a b", data: {} }] },
  { writes: [{ op: "set", col: "checks", id: "__proto__", data: {} }] },
  { writes: [{ op: "set", col: "checks", id: "a", data: { status: "finished" } }] },
  { writes: [{ op: "set", col: "checks", id: "a", data: { note: "x".repeat(9000) } }] },
  { writes: [{ op: "set", col: "checks", id: "a", data: [1, 2] }] },
  '{"writes":[{"op":"set","col":"checks","id":"a","data":{"__proto__":{"polluted":true}}}]}',
  "not json"
];
for (const body of bad) assert.equal((await handle(req("POST", body), s, env)).status, 400, "refused: " + JSON.stringify(body).slice(0, 60));
assert.equal({}.polluted, undefined, "no prototype pollution");
assert.equal((await handle(req("PUT", {}), s, env)).status, 405);

// every document ONE SUPREME wrote so far passes the same checks, so it can keep writing in this shape
const fresh = memStore();
for (const col of ["checks", "custom", "plan", "log", "meta"]) {
  const writes = Object.entries(seed[col]).map(([id, data]) => ({ op: "set", col, id, data }));
  for (let i = 0; i < writes.length; i += 50) {
    const res = await post(fresh, writes.slice(i, i + 50));
    assert.equal(res.status, 200, `seed ${col} batch ${i / 50}: ${await res.clone().text()}`);
  }
}
console.log("board.mjs self-check passed");
