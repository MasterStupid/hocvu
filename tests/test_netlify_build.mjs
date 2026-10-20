import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { configureProxy, proxyRedirect } from "../scripts/prepare-netlify.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const env = { HOCVU_API_URL: "https://gateway.example/base/", HOCVU_API_TOKEN: "synthetic-only-token" };

test("repeated preparation commands do not rewrite netlify.toml or log the token", () => {
  const config = new URL("../netlify.toml", import.meta.url);
  const before = readFileSync(config, "utf8");
  for (let count = 0; count < 2; count++) {
    const stdout = execFileSync(process.execPath, ["scripts/prepare-netlify.mjs"], { cwd: root, env, encoding: "utf8" });
    assert.match(stdout, /Validated Netlify API proxy for gateway.example/);
    assert.ok(!stdout.includes(env.HOCVU_API_TOKEN));
    assert.equal(readFileSync(config, "utf8"), before);
  }
});

test("in-memory redirect configuration is idempotent and preserves unrelated routes", () => {
  const config = { redirects: [{ from: "/other", to: "/elsewhere" }] };
  configureProxy(config, env);
  const first = JSON.stringify(config);
  configureProxy(config, env);
  assert.equal(JSON.stringify(config), first);
  assert.equal(config.redirects.length, 2);
  assert.equal(config.redirects[0].to, "https://gateway.example/base/api/:splat");
  assert.equal(config.redirects[0].headers["X-HocVu-Token"], env.HOCVU_API_TOKEN);
  configureProxy(config, { ...env, HOCVU_API_TOKEN: "replacement-synthetic-token" });
  assert.equal(config.redirects[0].headers["X-HocVu-Token"], "replacement-synthetic-token");
  assert.equal(config.redirects.length, 2);
});

test("the configured Netlify pre-build hook actually injects the proxy", () => {
  const toml = readFileSync(new URL("../netlify.toml", import.meta.url), "utf8");
  assert.match(toml, /\[\[plugins\]\]\s*package = "\.\/scripts\/netlify-proxy"/);
  execFileSync(process.execPath, ["--input-type=module", "-e", `
    import assert from "node:assert/strict";
    import plugin from "./scripts/netlify-proxy/index.js";
    const config = { redirects: [] };
    await plugin.onPreBuild({ netlifyConfig: config });
    await plugin.onPreBuild({ netlifyConfig: config });
    assert.equal(config.redirects.length, 1);
    assert.equal(config.redirects[0].headers["X-HocVu-Token"], "synthetic-only-token");
    assert.equal(config.redirects[0].status, 200);
    assert.equal(config.redirects[0].force, true);
  `], { cwd: root, env });
});

test("invalid settings fail without including supplied values in errors", () => {
  for (const invalid of [
    {}, { ...env, HOCVU_API_TOKEN: "" },
    { ...env, HOCVU_API_URL: "http://gateway.example" },
    { ...env, HOCVU_API_URL: "https://user:password@gateway.example" },
    { ...env, HOCVU_API_URL: "https://gateway.example?key=secret" },
    { ...env, HOCVU_API_TOKEN: "a\r\nInjected: value" },
  ]) {
    assert.throws(() => proxyRedirect(invalid), error => {
      assert.ok(!error.message.includes("synthetic-only-token"));
      assert.ok(!error.message.includes("password@"));
      return true;
    });
  }
});
