import { readFile, writeFile } from "node:fs/promises";

const configPath = new URL("../netlify.toml", import.meta.url);
const apiUrl = (process.env.HOCVU_API_URL || "").trim().replace(/\/+$/, "");
const apiToken = (process.env.HOCVU_API_TOKEN || "").trim();

if (!apiUrl || !apiToken) {
  throw new Error(
    "Set HOCVU_API_URL and HOCVU_API_TOKEN in Netlify before deploying."
  );
}

let parsed;
try {
  parsed = new URL(apiUrl);
} catch {
  throw new Error("HOCVU_API_URL must be a full HTTPS URL, for example https://hocvu-api.onrender.com");
}
if (parsed.protocol !== "https:") {
  throw new Error("HOCVU_API_URL must use HTTPS in production.");
}

const config = await readFile(configPath, "utf8");
if (!config.includes("HOCVU_API_URL_PLACEHOLDER") || !config.includes("HOCVU_API_TOKEN_PLACEHOLDER")) {
  throw new Error("Netlify redirect placeholders are missing; restore netlify.toml from Git.");
}

// JSON string escaping is also valid for TOML basic strings and prevents a
// quote or backslash in a token from changing the generated configuration.
const tomlString = (value) => JSON.stringify(value).slice(1, -1);
const rendered = config
  .replaceAll("HOCVU_API_URL_PLACEHOLDER", tomlString(apiUrl))
  .replaceAll("HOCVU_API_TOKEN_PLACEHOLDER", tomlString(apiToken));

await writeFile(configPath, rendered, "utf8");
console.log("Configured Netlify API proxy for", parsed.hostname);
