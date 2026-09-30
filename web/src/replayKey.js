// The file a recorded run keeps a GET response in (tools/record_run.py route_key, the same
// rules): the path without its leading slash, the query's parameters sorted with a signed
// link's sig and exp dropped, every character but letters, digits, "." and "-" written as
// "_" and its UTF-8 bytes in hex; a long name cut and given a hash of the whole.
// test/data/replay_keys.json holds the vectors both are tested with.
const DROPPED = new Set(["sig", "exp"]);

function fnv1a(text) {
  let h = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(text)) {
    h = Math.imul(h ^ byte, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

export function routeKey(pathAndQuery) {
  const url = new URL(pathAndQuery, "http://replay.invalid");
  const pairs = [...url.searchParams.entries()].filter(([k]) => !DROPPED.has(k))
    .sort(([a, x], [b, y]) => (a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0));
  const text = decodeURIComponent(url.pathname).replace(/^\/+|\/+$/g, "")
    + (pairs.length ? `?${pairs.map(([k, v]) => `${k}=${v}`).join("&")}` : "");
  let key = "";
  for (const c of text) {
    if (/^[A-Za-z0-9.-]$/.test(c)) key += c;
    else for (const b of new TextEncoder().encode(c)) key += `_${b.toString(16).padStart(2, "0")}`;
  }
  return key.length <= 150 ? key : `${key.slice(0, 100)}-${fnv1a(key)}`;
}
