import type { Investigation, KnowledgeDocument, LoginResponse, PaginatedInvestigations } from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

let accessToken: string | null = sessionStorage.getItem('rod_token');
let onAuthLost: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
  if (token) sessionStorage.setItem('rod_token', token);
  else sessionStorage.removeItem('rod_token');
}

export function getAccessToken() {
  return accessToken;
}

export function onAuthenticationLost(cb: () => void) {
  onAuthLost = cb;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function parseErrorDetail(res: Response): Promise<unknown> {
  try {
    const body = await res.json();
    return body.detail ?? body.error ?? body;
  } catch {
    return res.statusText;
  }
}

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        });
        if (!res.ok) return false;
        const data: LoginResponse = await res.json();
        setAccessToken(data.token);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined> | InvestigationFilters;
  skipAuth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions['query']) {
  const url = new URL(path, API_BASE);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<T>(path: string, options: RequestOptions = {}, isRetry = false): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (accessToken && !options.skipAuth) headers.Authorization = `Bearer ${accessToken}`;

  const res = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    credentials: 'include',
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 401 && !options.skipAuth && !isRetry) {
    const refreshed = await tryRefresh();
    if (refreshed) return request<T>(path, options, true);
    setAccessToken(null);
    onAuthLost?.();
    throw new ApiError(401, 'Session expired');
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const data = await request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: { username, password },
    skipAuth: true,
  });
  setAccessToken(data.token);
  return data;
}

export async function logout(): Promise<void> {
  try {
    await request('/auth/logout', { method: 'POST' });
  } finally {
    setAccessToken(null);
  }
}

export interface InvestigationFilters {
  page?: number;
  per_page?: number;
  status?: string;
  store_id?: string;
  sku?: string;
}

export function listInvestigations(filters: InvestigationFilters = {}) {
  return request<PaginatedInvestigations>('/api/v1/detective/investigations', { query: filters });
}

export function getInvestigation(id: number) {
  return request<Investigation>(`/api/v1/detective/investigation/${id}`);
}

export interface NewInvestigationPayload {
  query: string;
  context?: { store_id?: string; sku?: string };
}

export function createInvestigation(payload: NewInvestigationPayload) {
  return request<Investigation>('/api/v1/detective/investigate', {
    method: 'POST',
    body: payload,
  });
}

export function getReport(investigationId: number) {
  return request<import('./types').Report & { human_readable_summary: string }>(
    `/api/v1/detective/report/${investigationId}`,
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function exportReport(investigationId: number, format: 'json' | 'pdf') {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(
    buildUrl(`/api/v1/detective/report/${investigationId}/export`, { format }),
    { headers, credentials: 'include' },
  );
  if (!res.ok) throw new ApiError(res.status, await parseErrorDetail(res));

  if (format === 'json') {
    const data = await res.json();
    downloadBlob(
      new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
      `INV-${investigationId}-report.json`,
    );
    return;
  }

  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `INV-${investigationId}-report.pdf`;
  downloadBlob(blob, filename);
}

export function listKnowledgeDocuments() {
  return request<{ documents: KnowledgeDocument[] }>('/api/v1/detective/knowledge');
}

export interface KnowledgeDocumentPayload {
  document_text: string;
  category: 'SOP' | 'Past Case';
  tags?: string[];
}

export function createKnowledgeDocument(payload: KnowledgeDocumentPayload) {
  return request('/api/v1/detective/knowledge', { method: 'POST', body: payload });
}

export function updateKnowledgeDocument(documentId: string, payload: KnowledgeDocumentPayload) {
  return request(`/api/v1/detective/knowledge/${documentId}`, { method: 'PUT', body: payload });
}

export function deleteKnowledgeDocument(documentId: string) {
  return request(`/api/v1/detective/knowledge/${documentId}`, { method: 'DELETE' });
}