import type { ApiEnvelope, ProblemDetails } from "./types";

export class ApiError extends Error {
  problem: ProblemDetails;

  constructor(problem: ProblemDetails) {
    super(problem.detail || problem.title);
    this.problem = problem;
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  csrfToken?: string | null,
): Promise<ApiEnvelope<T>> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({
      title: "Request failed",
      detail: `HTTP ${response.status}`,
      code: "http_error",
      request_id: "unknown",
    }))) as ProblemDetails;
    throw new ApiError(problem);
  }
  return (await response.json()) as ApiEnvelope<T>;
}

