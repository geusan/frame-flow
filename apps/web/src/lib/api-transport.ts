export interface ApiTransport {
  readonly baseUrl: string;
  send(path: string, init?: RequestInit): Promise<Response>;
}

export function createBrowserTransport(baseUrl: string, embedRoot = ""): ApiTransport {
  function resolvedBase() {
    if (typeof window === "undefined" || !embedRoot || !window.location.pathname.startsWith(embedRoot)) return baseUrl;
    const workspace = window.location.pathname.slice(embedRoot.length).split("/")[0];
    return /^[A-Za-z0-9_-]{1,64}$/.test(workspace) ? `${baseUrl}/w/${workspace}` : baseUrl;
  }
  return {
    get baseUrl() { return resolvedBase(); },
    async send(path, init) {
      const headers = new Headers(init?.headers);
      if (init?.method === "POST" && (path === "/canvas-runs" || /^\/workflows\/[^/]+\/runs$/.test(path))) headers.set("X-Idempotency-Key", crypto.randomUUID());
      if (typeof document !== "undefined" && !["GET", "HEAD", "OPTIONS"].includes(init?.method ?? "GET")) {
        const csrf = document.cookie.split(";").map(value => value.trim()).find(value => value.startsWith("service_csrf="));
        if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf.slice("service_csrf=".length)));
      }
      const response = await fetch(`${resolvedBase()}${path}`, { ...init, headers, credentials: "same-origin", cache: "no-store" });
      if (response.status === 401 && typeof window !== "undefined" && embedRoot) {
        window.parent.dispatchEvent(new Event("service:session-expired"));
      }
      return response;
    },
  };
}
