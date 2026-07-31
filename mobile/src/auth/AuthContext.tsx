import React, { createContext, useContext, useEffect, useState } from "react";

import { login as apiLogin } from "../api/auth";
import { clearToken, getRole, getToken, Role } from "../api/client";

interface AuthContextValue {
  isLoggedIn: boolean;
  isLoading: boolean;
  role: Role;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [role, setRoleState] = useState<Role>("tradie");

  useEffect(() => {
    Promise.all([getToken(), getRole()])
      .then(([token, currentRole]) => {
        setIsLoggedIn(Boolean(token));
        setRoleState(currentRole);
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    await apiLogin(username, password);
    setIsLoggedIn(true);
    setRoleState(await getRole());
  };

  const logout = async () => {
    await clearToken();
    setIsLoggedIn(false);
    setRoleState("tradie");
  };

  return (
    <AuthContext.Provider value={{ isLoggedIn, isLoading, role, login, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
