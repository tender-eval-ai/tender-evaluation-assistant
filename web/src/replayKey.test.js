// The same vectors tools/record_run.py is tested with (test/test_record_run.py).
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { routeKey } from "./replayKey.js";

const here = dirname(fileURLToPath(import.meta.url));
const vectors = JSON.parse(readFileSync(resolve(here, "../../test/data/replay_keys.json"), "utf8"));

describe("routeKey", () => {
  it.each(vectors.map((v) => [v.path, v.key]))("%s", (path, key) => {
    expect(routeKey(path)).toBe(key);
  });
});
