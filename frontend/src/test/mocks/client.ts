/**
 * Jest stand-in for `@/api/client`.
 *
 * The real client reads `import.meta.env`, which Jest (CommonJS) cannot parse.
 * Tests never perform real HTTP, so this module provides the same surface
 * (token store, ApiError, base URL) with inert implementations.
 */
import type { AxiosInstance } from 'axios';

export const API_BASE_URL = '/';

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
    return null;
  },
  getRefresh(): string | null {
    return null;
  },
  set(): void {
    return undefined;
  },
  clear(): void {
    return undefined;
  },
};

/** Inert axios instance. Tests must mock the concrete API functions instead. */
export const http = {} as AxiosInstance;
