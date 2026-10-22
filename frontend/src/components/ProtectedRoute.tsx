/** Route guard: redirects anonymous users to the login page. */
import { Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';

import { LoadingState } from '@/components/Feedback';
import { useAuth } from '@/hooks/useAuth';

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, initialised } = useAuth();
  const location = useLocation();

  if (!initialised) {
    return <LoadingState label="Restoring your session…" />;
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
