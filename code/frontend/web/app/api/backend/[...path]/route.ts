import { NextRequest } from "next/server";

type RuntimeBindings = { GAME_BACKEND_URL?: string };

const backendBase = async () => {
  let runtimeUrl = "";
  try {
    const { env } = await import("cloudflare:workers");
    runtimeUrl = (env as unknown as RuntimeBindings).GAME_BACKEND_URL || "";
  } catch { /* non-Worker runtimes use the server environment fallback */ }
  const configuredUrl = runtimeUrl || process.env.GAME_BACKEND_URL || "http://127.0.0.1:8100";
  return configuredUrl.replace(/\/$/, "");
};

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = new URL(`${await backendBase()}/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.delete("accept-encoding");
  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      redirect: "manual",
    });
    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch {
    return Response.json({
      error: {
        code: "BACKEND_PROXY_UNAVAILABLE",
        message: "游戏服务暂时无法连接，请稍后重试。",
        details: {},
      },
    }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
