/**
 * Authentication hook. Owns session bootstrap, login and logout, and reacts to
 * the "session expired" event emitted by the axios interceptor.
 */
import { useCallback, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';

import { SESSION_EXPIRED_EVENT, tokenStore } from '@/api/client';
import { authApi } from '@/api/endpoints';
import { clearSession, setSession, setUser, useAppDispatch, useAppSelector } from '@/store';

export function useAuth() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user, accessToken, initialised } = useAppSelector((state) => state.auth);

  // Bootstrap: if a token exists, resolve the current user.
  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      const token = tokenStore.getAccess();
      if (!token) {
        dispatch(setUser(null));
        return;
      }
      try {
        const me = await authApi.me();
        if (!cancelled) dispatch(setUser(me));
      } catch {
        if (!cancelled) dispatch(clearSession());
      }
    }
    if (!initialised) void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [dispatch, initialised]);

  // Global session-expiry handling.
  useEffect(() => {
    function onExpired() {
      dispatch(clearSession());
      queryClient.clear();
      toast.error('Your session expired. Please sign in again.');
      navigate('/login', { replace: true });
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [dispatch, navigate, queryClient]);

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await authApi.login(username, password);
      dispatch(
        setSession({ user: result.user, access: result.access, refresh: result.refresh }),
      );
      return result.user;
    },
    [dispatch],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Logout is best effort; the client clears local state regardless.
    }
    dispatch(clearSession());
    queryClient.clear();
    navigate('/login', { replace: true });
  }, [dispatch, navigate, queryClient]);

  /**
   * Permission gate for UI affordances. The backend enforces the same keys, so
   * this only hides what the API would reject anyway.
   */
  const can = useCallback(
    (permission: string) =>
      Boolean(user?.effective_permissions?.includes(permission)),
    [user?.effective_permissions],
  );

  return {
    user,
    permissions: user?.effective_permissions ?? [],
    can,
    isAuthenticated: Boolean(user && accessToken),
    initialised,
    organizationId: user?.organization_id ?? null,
    login,
    logout,
  };
}
