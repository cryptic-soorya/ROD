import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

export default function RequireAuth({ children, scope }: { children: ReactNode; scope?: string }) {
  const { isAuthenticated, hasScope } = useAuth();

  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (scope && !hasScope(scope)) return <Navigate to="/investigations" replace />;

  return <>{children}</>;
}
