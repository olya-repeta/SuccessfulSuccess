import { getAccessToken, signOut } from "@/lib/auth";
import type {
  AgendaParseResponse,
  ApiErrorBody,
  ApiErrorDetail,
  Meeting,
  MeetingCreateInput,
  MeetingList,
  UserProfile,
} from "@/lib/types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const AGENDA_PARSER_URL =
  process.env.NEXT_PUBLIC_AGENDA_PARSER_URL ?? "";

export class ApiError extends Error {
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly status: number;

  constructor(
    status: number,
    code: string,
    message: string,
    details: ApiErrorDetail[],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the meetings API.",
      [],
    );
  }

  // The session is gone or was revoked: sign out, and the auth guard sends the
  // user back to the login page.
  if (response.status === 401) {
    void signOut();
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const body = payload as ApiErrorBody | null;
    throw new ApiError(
      response.status,
      body?.error?.code ?? "internal_error",
      body?.error?.message ?? `Request failed with status ${response.status}.`,
      body?.error?.details ?? [],
    );
  }

  return payload as T;
}

export function listMeetings(params: { date?: string; q?: string } = {}) {
  const search = new URLSearchParams();
  if (params.date) search.set("date", params.date);
  if (params.q) search.set("q", params.q);
  const query = search.toString();
  return request<MeetingList>(`/api/v1/meetings${query ? `?${query}` : ""}`);
}

export function getMeeting(id: string) {
  return request<Meeting>(`/api/v1/meetings/${id}`);
}

export function createMeeting(payload: MeetingCreateInput) {
  return request<Meeting>("/api/v1/meetings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateMeeting(id: string, payload: MeetingCreateInput) {
  return request<Meeting>(`/api/v1/meetings/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteMeeting(id: string) {
  return request<void>(`/api/v1/meetings/${id}`, { method: "DELETE" });
}

export function getMe() {
  return request<UserProfile>("/api/v1/me");
}

/** Stores the profile from the ID token in the users table; call after signing in. */
export function syncMe(idToken: string) {
  return request<UserProfile>("/api/v1/me/sync", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  });
}

/** Calls the Parser Lambda Function URL directly with user's Cognito Bearer token. */
export async function parseAgenda(params: {
  text: string;
  today?: string;
  tz?: string;
  signal?: AbortSignal;
}): Promise<AgendaParseResponse> {
  const parserUrl = AGENDA_PARSER_URL;
  if (!parserUrl) {
    throw new ApiError(
      0,
      "config_error",
      "Agenda parser URL is not configured. Please set NEXT_PUBLIC_AGENDA_PARSER_URL.",
      [],
    );
  }

  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(
      401,
      "unauthorized",
      "You must be signed in to parse agendas.",
      [],
    );
  }

  const today = params.today ?? new Date().toISOString().slice(0, 10);
  const tz =
    params.tz ??
    (typeof Intl !== "undefined"
      ? Intl.DateTimeFormat().resolvedOptions().timeZone
      : "UTC") ??
    "UTC";

  let response: Response;
  try {
    response = await fetch(parserUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        text: params.text,
        today,
        tz,
      }),
      signal: params.signal,
    });
  } catch (err: unknown) {
    if (
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError")
    ) {
      throw err;
    }
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the agenda parser. Please check your network connection.",
      [],
    );
  }

  if (response.status === 401) {
    void signOut();
    throw new ApiError(
      401,
      "unauthorized",
      "Your session has expired. Please sign in again.",
      [],
    );
  }

  const rawText = await response.text();
  let payload: Record<string, unknown> | null = null;
  try {
    payload = rawText ? (JSON.parse(rawText) as Record<string, unknown>) : null;
  } catch {
    // payload is not json
  }

  if (!response.ok) {
    let message =
      (typeof payload?.detail === "string" ? payload.detail : null) ??
      (typeof payload?.message === "string" ? payload.message : null);
    let code = "parser_error";

    if (response.status === 413) {
      code = "text_too_long";
      message =
        message ?? "Input text is too long (maximum 10,000 characters).";
    } else if (response.status === 422) {
      code = "parse_failed";
      message =
        message ??
        "Failed to parse an agenda from the provided text. Please try adjusting the format.";
    } else if (response.status === 429) {
      code = "throttled";
      message = "Too many requests. Please wait a moment and try again.";
    }

    throw new ApiError(
      response.status,
      code,
      message ?? `Parser request failed with status ${response.status}.`,
      [],
    );
  }

  return payload as unknown as AgendaParseResponse;
}
