export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type NpcStreamEvent = {
  type: "stream_start" | "npc_thinking_start" | "npc_thinking_end" | "npc_start" | "npc_delta" | "npc_end" | "complete" | "error";
  stream_id?: string;
  npc_id?: string;
  npc_name?: string;
  delta?: string;
  result?: Record<string, unknown>;
  code?: string;
  message?: string;
};

const SANDBOX_ACCOUNT_KEY = "qingjiang-sandbox-account";

function browserCookieValue(name: string) {
  if (typeof document === "undefined") return "";
  const prefix = `${name}=`;
  const value = document.cookie
    .split(";")
    .map(part => part.trim())
    .find(part => part.startsWith(prefix))
    ?.slice(prefix.length);
  return value ? decodeURIComponent(value) : "";
}

function browserSandboxAccountId() {
  if (typeof window === "undefined") return "";
  let accountId = "";
  try { accountId = localStorage.getItem(SANDBOX_ACCOUNT_KEY) || ""; } catch { /* storage may be disabled */ }
  accountId ||= browserCookieValue(SANDBOX_ACCOUNT_KEY);
  accountId ||= `sandbox_web_${crypto.randomUUID().replaceAll("-", "")}`;
  try { localStorage.setItem(SANDBOX_ACCOUNT_KEY, accountId); } catch { /* cookie remains as fallback */ }
  document.cookie = `${SANDBOX_ACCOUNT_KEY}=${encodeURIComponent(accountId)}; Path=/; Max-Age=31536000; SameSite=Lax`;
  return accountId;
}

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(message: string, code = "CLIENT_HTTP_ERROR", status = 0, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export class GameApi {
  baseUrl: string;
  csrfToken = "";
  streamIdleTimeoutMs = 120_000;
  accountId = "";

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  key(prefix: string) {
    return `web-${prefix}-${crypto.randomUUID()}`;
  }

  setAccountId(accountId: string) {
    this.accountId = accountId;
  }

  enableSandboxAccount() {
    this.accountId = browserSandboxAccountId();
    return this.accountId;
  }

  setCsrfToken(token: string, cookieName = "serious_game_session_csrf") {
    this.csrfToken = token;
    if (typeof sessionStorage !== "undefined") sessionStorage.setItem("qingjiang-csrf", token);
    if (typeof document !== "undefined") {
      document.cookie = `${cookieName}=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
    }
  }

  restoreCsrf(cookieName: string) {
    const value = browserCookieValue(cookieName)
      || (typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem("qingjiang-csrf") || "");
    this.csrfToken = value;
    if (value && typeof sessionStorage !== "undefined") sessionStorage.setItem("qingjiang-csrf", value);
    return value;
  }

  clearCsrf(cookieName: string) {
    this.csrfToken = "";
    if (typeof sessionStorage !== "undefined") sessionStorage.removeItem("qingjiang-csrf");
    if (typeof document !== "undefined") document.cookie = `${cookieName}=; Path=/; Max-Age=0; SameSite=Lax`;
  }

  async request<T = Record<string, unknown>>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json; charset=utf-8";
    if (this.accountId) headers["X-Account-ID"] = this.accountId;
    if (this.csrfToken && !["GET", "HEAD"].includes(method)) headers["X-CSRF-Token"] = this.csrfToken;
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        credentials: "include",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError("游戏服务暂时无法连接，请稍后重试。", "CLIENT_CONNECTION_ERROR");
    }
    const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = (data as { error?: Record<string, unknown> }).error ?? {};
      throw new ApiError(
        String(error.message ?? "这项操作暂时无法完成，请稍后重试。"),
        String(error.code ?? "CLIENT_HTTP_ERROR"),
        response.status,
        (error.details as Record<string, unknown>) ?? {},
      );
    }
    return data as T;
  }

  async streamWrite(
    sessionId: string,
    suffix: string,
    body: Record<string, unknown>,
    onEvent: (event: NpcStreamEvent) => void,
  ) {
    const headers: Record<string, string> = {
      Accept: "application/x-ndjson",
      "Content-Type": "application/json; charset=utf-8",
    };
    if (this.accountId) headers["X-Account-ID"] = this.accountId;
    if (this.csrfToken) headers["X-CSRF-Token"] = this.csrfToken;
    const controller = new AbortController();
    let timedOut = false;
    let timeout: ReturnType<typeof setTimeout>;
    const resetTimeout = () => {
      clearTimeout(timeout);
      timeout = setTimeout(() => { timedOut = true; controller.abort(); }, this.streamIdleTimeoutMs);
    };
    resetTimeout();
    try {
      let response: Response;
      try {
        response = await fetch(
          `${this.baseUrl}/api/game/session/${encodeURIComponent(sessionId)}${suffix}`,
          { method: "POST", headers, credentials: "include", body: JSON.stringify(body), signal: controller.signal },
        );
      } catch {
        throw new ApiError("游戏服务暂时无法连接，请稍后重试。", "CLIENT_CONNECTION_ERROR");
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const error = (data as { error?: Record<string, unknown> }).error ?? {};
        throw new ApiError(
          String(error.message ?? "这项操作暂时无法完成，请稍后重试。"),
          String(error.code ?? "CLIENT_HTTP_ERROR"),
          response.status,
          (error.details as Record<string, unknown>) ?? {},
        );
      }
      if (!response.body) throw new ApiError("NPC 回应流未建立。", "CLIENT_STREAM_UNAVAILABLE");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      let result: Record<string, unknown> | null = null;
      const streamState: { error: NpcStreamEvent | null } = { error: null };
      const consume = (line: string) => {
        if (!line.trim()) return;
        const event = JSON.parse(line) as NpcStreamEvent;
        onEvent(event);
        if (event.type === "complete" && event.result) result = event.result;
        if (event.type === "error") streamState.error = event;
      };
      while (true) {
        const { done, value } = await reader.read();
        if (value?.length) resetTimeout();
        pending += decoder.decode(value, { stream: !done });
        const lines = pending.split("\n");
        pending = lines.pop() || "";
        lines.forEach(consume);
        if (done || result || streamState.error) break;
      }
      consume(pending);
      void reader.cancel().catch(() => {});
      if (streamState.error) throw new ApiError(streamState.error.message || "对方暂时无法回应，请稍后重试。", streamState.error.code || "NPC_RESPONSE_UNAVAILABLE", 503);
      if (!result) throw new ApiError("NPC 回应流提前结束。", "CLIENT_STREAM_INCOMPLETE");
      return result;
    } catch (error) {
      if (timedOut) throw new ApiError("等待人物回应超时，正在核对最新进度。请确认记录后再决定是否重试。", "CLIENT_STREAM_TIMEOUT");
      throw error;
    } finally {
      clearTimeout(timeout!);
      controller.abort();
    }
  }

  auth(mode: "login" | "register", username: string, password: string) {
    return this.request<{ account_id: string; username: string; csrf_token: string }>("POST", `/api/auth/${mode}`, { username, password });
  }
  logout() { return this.request("POST", "/api/auth/logout"); }
  me() { return this.request<{ account_id: string; username: string; roles: string[] }>("GET", "/api/auth/me"); }
  health() { return this.request<{ terminal_protocol_version?: string }>("GET", "/health/live"); }
  ready() { return this.request<{ authentication_required?: boolean; self_registration?: boolean; csrf_cookie_name?: string; model_consent_required?: boolean }>("GET", "/health/ready"); }
  aiConfiguration() { return this.request<Record<string, unknown>>("GET", "/api/ai/config"); }
  configureAI(value: { mode: "personal" | "server_default"; base_url?: string; api_key?: string; model?: string }) {
    return this.request<Record<string, unknown>>("PUT", "/api/ai/config", value);
  }
  clearAIConfiguration() { return this.request<Record<string, unknown>>("DELETE", "/api/ai/config"); }
  consent() { return this.request<Record<string, unknown>>("GET", "/api/consent/current"); }
  signConsent(consentVersion: string) {
    return this.request<Record<string, unknown>>("POST", "/api/consent", {
      consent_version: consentVersion,
      scopes: ["service_storage", "third_party_model"],
    });
  }
  withdrawConsent(reason = "玩家主动撤回模型处理授权") {
    return this.request<Record<string, unknown>>("POST", "/api/consent/withdraw", { reason });
  }
  origins() { return this.request<{ origins?: Record<string, unknown>[] }>("GET", "/api/game/origins"); }
  newSession(originId?: string) {
    return this.request<Record<string, unknown>>("POST", "/api/game/session", {
      client_request_id: this.key("new"),
      ...(originId ? { origin_id: originId } : {}),
    });
  }
  latest() { return this.request<Record<string, unknown>>("GET", "/api/game/session/latest-active"); }
  async sessions() {
    try {
      return await this.request<{ sessions: Record<string, unknown>[] }>("GET", "/api/game/sessions");
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      const latest = await this.latest();
      const story = latest.story as Record<string, unknown> | undefined;
      return {
        sessions: latest.session_id ? [{
          session_id: latest.session_id,
          story_day: story?.day || 1,
          status: latest.status || "active",
          updated_at: latest.updated_at || "",
        }] : [],
      };
    }
  }
  view(sessionId: string, after = 0) { return this.request<Record<string, unknown>>("GET", `/api/game/session/${encodeURIComponent(sessionId)}/view?after=${after}`); }
  conversations(sessionId: string, filters: { npc_id?: string; story_day?: number; cursor?: string; limit?: number } = {}) {
    const query = new URLSearchParams();
    if (filters.npc_id) query.set("npc_id", filters.npc_id);
    if (filters.story_day) query.set("story_day", String(filters.story_day));
    if (filters.cursor) query.set("cursor", filters.cursor);
    if (filters.limit) query.set("limit", String(filters.limit));
    return this.request<{ items: Record<string, unknown>[]; next_cursor?: string | null }>("GET", `/api/game/session/${encodeURIComponent(sessionId)}/conversations?${query}`);
  }
  async completeConversationHistory(sessionId: string, filters: { npc_id?: string; story_day?: number; limit?: number } = {}) {
    const items: Record<string, unknown>[] = [];
    let cursor: string | undefined;
    do {
      const page = await this.conversations(sessionId, { ...filters, cursor });
      items.push(...(Array.isArray(page.items) ? page.items : []));
      cursor = page.next_cursor || undefined;
    } while (cursor);
    return items;
  }
  session(sessionId: string) { return this.request<Record<string, unknown>>("GET", `/api/game/session/${encodeURIComponent(sessionId)}`); }
  panel(sessionId: string, name: string) { return this.request<Record<string, unknown>>("GET", `/api/game/session/${encodeURIComponent(sessionId)}/${name}`); }
  referenceDocuments(sessionId: string) {
    return this.request<{ documents: import("../ReferenceDocuments").ReferenceDocument[] }>("GET", `/api/game/session/${encodeURIComponent(sessionId)}/governance/reference-documents`);
  }

  archiveDetail(sessionId: string, archiveId: string) {
    return this.request<Record<string, unknown>>(
      "GET",
      `/api/game/session/${encodeURIComponent(sessionId)}/governance/archives/${encodeURIComponent(archiveId)}`,
    );
  }
  contractDetail(sessionId: string, contractId: string) {
    return this.request<Record<string, unknown>>(
      "GET",
      `/api/game/session/${encodeURIComponent(sessionId)}/governance/contracts/${encodeURIComponent(contractId)}`,
    );
  }
  manualSave(sessionId: string, body: Record<string, unknown>) {
    return this.request<Record<string, unknown>>("POST", `/api/game/session/${encodeURIComponent(sessionId)}/manual-saves`, body);
  }
  loadSnapshot(sessionId: string, body: Record<string, unknown>) {
    return this.request<Record<string, unknown>>("POST", `/api/game/session/${encodeURIComponent(sessionId)}/load-snapshot`, body);
  }
  validation() { return this.request<Record<string, unknown>>("GET", "/api/game/package/validation"); }
  write(sessionId: string, suffix: string, method: "POST" | "PUT", body: Record<string, unknown>) {
    return this.request<Record<string, unknown>>(method, `/api/game/session/${encodeURIComponent(sessionId)}${suffix}`, body);
  }
  action(sessionId: string, body: Record<string, unknown>) {
    return this.write(sessionId, "/action", "POST", body);
  }
}
