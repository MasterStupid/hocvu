import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export function proxyRedirect(env = process.env) {
  const apiUrl = (env.HOCVU_API_URL || "").trim().replace(/\/+$/, "");
  const apiToken = (env.HOCVU_API_TOKEN || "").trim();
  if (!apiUrl || !apiToken) {
    throw new Error("Set HOCVU_API_URL and HOCVU_API_TOKEN in Netlify before deploying.");
  }
  let parsed;
  try {
    parsed = new URL(apiUrl);
  } catch {
    throw new Error("HOCVU_API_URL must be a full HTTPS URL.");
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("HOCVU_API_URL must use HTTPS without credentials, query or fragment.");
  }
  if (/[\r\n\0]/.test(apiToken)) throw new Error("HOCVU_API_TOKEN contains invalid header characters.");
  return {
    from: "/api/*", to: `${apiUrl}/api/:splat`, status: 200, force: true,
    headers: { "X-HocVu-Token": apiToken },
  };
}

export function configureProxy(netlifyConfig, env = process.env) {
  const redirect = proxyRedirect(env);
  netlifyConfig.redirects = [
    redirect, ...(netlifyConfig.redirects || []).filter(rule => rule.from !== "/api/*"),
  ];
}

// The build plugin supplies the redirect in memory. This command only validates
// settings: repeated builds never rewrite tracked files or persist credentials.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log("Validated Netlify API proxy for", new URL(proxyRedirect().to).hostname);
}
