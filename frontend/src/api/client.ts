/**
 * Axios client with request/response interceptors.
 *
 * - attaches the access token to every request,
 * - transparently refreshes an expired access token once (single-flight),
 * - normalises every error into an `ApiError` for consistent UI handling,
 * - emits a global event when the session becomes unrecoverable.
 */
import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios';

const ACCESS_TOKEN_KEY = 'hs.access_token';
const REFRESH_TOKEN_KEY = 'hs.refresh_token';

export const SESSION_EXPIRED_EVENT = 'hs:session-expired';

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export const tokenStore = {
  getAccess(): string | null {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  },
  getRefresh(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  },
  set(access: string, refresh?: string): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, access);
    if (refresh) {
      localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
    }
  },
  clear(): void {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/';

export const http: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  // AI generation can take ~90s with reasoning models; keep this above the
  // backend's 120s provider timeout so the UI receives the real response.
  timeout: 150000,
  headers: { 'Content-Type': 'application/json' },
});

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccess();
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  return config;
});

let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStore.getRefresh();
  if (!refresh) {
    throw new ApiError('No refresh token available', 401);
  }
  const response = await axios.post<{ access: string }>(
    `${API_BASE_URL}/api/v1/auth/refresh`,
    { refresh_token: refresh },
    { headers: { 'Content-Type': 'application/json' } },
  );
  tokenStore.set(response.data.access);
  return response.data.access;
}

function normaliseError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0;
  const data = error.response?.data as { detail?: string; errors?: unknown } | undefined;
  let message = data?.detail ?? error.message;
  if (!message && status === 0) {
    message = 'Cannot reach the server. Check your connection.';
  }
  if (status === 429) {
    message = data?.detail ?? 'Too many requests. Please slow down.';
  }
  return new ApiError(message || 'Unexpected error', status, data);
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined;
    const status = error.response?.status;

    const isAuthRoute = original?.url?.includes('/api/v1/auth/');
    if (status === 401 && original && !original._retried && !isAuthRoute) {
      original._retried = true;
      try {
        refreshPromise = refreshPromise ?? refreshAccessToken();
        const newToken = await refreshPromise;
        refreshPromise = null;
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${newToken}` };
        return await http.request(original);
      } catch {
        refreshPromise = null;
        tokenStore.clear();
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
        return Promise.reject(normaliseError(error));
      }
    }
    return Promise.reject(normaliseError(error));
  },
);
