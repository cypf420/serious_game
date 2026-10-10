import http from "node:http";
import net from "node:net";
import { fileURLToPath } from "node:url";

import { startProdServer, tryServeStatic } from "vinext/server/prod-server";

const outDir = fileURLToPath(new URL("../dist", import.meta.url));
const clientDir = fileURLToPath(new URL("../dist/client", import.meta.url));
const port = Number(process.env.PORT || 3000);
const host = process.env.HOSTNAME || "0.0.0.0";

async function reserveFreePort() {
  const socket = net.createServer();
  await new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.listen(0, "127.0.0.1", resolve);
  });
  const address = socket.address();
  const freePort = typeof address === "object" && address ? address.port : 0;
  await new Promise((resolve, reject) => socket.close((error) => error ? reject(error) : resolve()));
  if (!freePort) throw new Error("Unable to reserve an internal production port");
  return freePort;
}

function proxyToVinext(req, res, internalPort) {
  const upstream = http.request({
    hostname: "127.0.0.1",
    port: internalPort,
    method: req.method,
    path: req.url,
    headers: req.headers,
  }, (upstreamResponse) => {
    res.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    upstreamResponse.pipe(res);
  });
  upstream.once("error", (error) => {
    if (res.headersSent) {
      res.destroy(error);
      return;
    }
    res.writeHead(502, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Production renderer unavailable");
  });
  req.pipe(upstream);
}

const internalPort = await reserveFreePort();
const { server: vinextServer } = await startProdServer({
  outDir,
  port: internalPort,
  host: "127.0.0.1",
});

const gateway = http.createServer(async (req, res) => {
  const rawUrl = req.url || "/";
  let pathname;
  try {
    pathname = new URL(rawUrl, "http://localhost").pathname;
  } catch {
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Bad Request");
    return;
  }

  // vinext 0.0.50 builds its production static-file cache with Windows path
  // separators. Serve dist/client through its guarded filesystem resolver so
  // browser URLs using forward slashes work on every platform.
  if (pathname !== "/" && await tryServeStatic(req, res, clientDir, pathname, true)) return;
  proxyToVinext(req, res, internalPort);
});

await new Promise((resolve, reject) => {
  gateway.once("error", reject);
  gateway.listen(port, host, resolve);
});
console.log(`[serious-game] Production gateway listening on http://${host}:${port}`);

let shuttingDown = false;
async function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  await Promise.all([
    new Promise((resolve) => gateway.close(() => resolve())),
    new Promise((resolve) => vinextServer.close(() => resolve())),
  ]);
}

process.once("SIGINT", () => void shutdown().then(() => process.exit(0)));
process.once("SIGTERM", () => void shutdown().then(() => process.exit(0)));
