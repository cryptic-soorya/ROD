import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { UserPublic } from '../lib/types';
import * as api from '../lib/api';

interface AuthContextValue {
  user: UserPublic | null;
  isAuthenticated: boolean;
  isReady: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasScope: (scope: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const USER_STORAGE_KEY = 'rod_user';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(() => {
    const raw = sessionStorage.getItem(USER_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as UserPublic) : null;
  });
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    api.onAuthenticationLost(() => {
      setUser(null);
      sessionStorage.removeItem(USER_STORAGE_KEY);
    });
    setIsReady(true);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: !!user,
      isReady,
      hasScope: (scope: string) => !!user?.scopes.includes(scope),
      login: async (username: string, password: string) => {
        const data = await api.login(username, password);
        setUser(data.user);
        sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(data.user));
      },
      logout: async () => {
        await api.logout();
        setUser(null);
        sessionStorage.removeItem(USER_STORAGE_KEY);
      },
    }),
    [user, isReady],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
