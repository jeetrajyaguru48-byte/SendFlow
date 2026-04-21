import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";

const TOKENS_KEY = "auth_tokens";
const ACTIVE_TOKEN_KEY = "active_auth_token";

type Account = {
  token: string;
  user: any;
};

type AuthContextValue = {
  token: string | null;
  tokens: string[];
  user: any;
  accounts: Account[];
  loading: boolean;
  initialized: boolean;
  error: string | null;
  isAuthenticated: boolean;
  login: (loginHint?: string) => Promise<void>;
  logout: (accountToken?: string) => void;
  switchAccount: (nextToken: string) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const readStoredTokens = (): string[] => {
  try {
    const raw = localStorage.getItem(TOKENS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((value) => typeof value === "string") : [];
  } catch {
    return [];
  }
};

const persistTokens = (tokens: string[], activeToken: string | null) => {
  localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  if (activeToken) {
    localStorage.setItem(ACTIVE_TOKEN_KEY, activeToken);
  } else {
    localStorage.removeItem(ACTIVE_TOKEN_KEY);
  }
};

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [tokens, setTokens] = useState<string[]>(() => readStoredTokens());
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(ACTIVE_TOKEN_KEY));
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const authToken = params.get("auth_token");

    if (authToken) {
      const updatedTokens = Array.from(new Set([...readStoredTokens(), authToken]));
      setTokens(updatedTokens);
      setToken(authToken);
      persistTokens(updatedTokens, authToken);
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (!token) {
      const storedTokens = readStoredTokens();
      const storedActiveToken = localStorage.getItem(ACTIVE_TOKEN_KEY);
      if (storedTokens.length > 0) {
        const activeToken = storedActiveToken && storedTokens.includes(storedActiveToken)
          ? storedActiveToken
          : storedTokens[0];
        setTokens(storedTokens);
        setToken(activeToken);
        persistTokens(storedTokens, activeToken);
      }
    }

    setInitialized(true);
  }, []);

  useEffect(() => {
    if (!initialized) return;

    if (!token || tokens.length === 0) {
      setAccounts([]);
      setUser(null);
      setLoading(false);
      persistTokens([], null);
      return;
    }

    const fetchAccounts = async () => {
      setLoading(true);
      try {
        const settled = await Promise.allSettled(
          tokens.map(async (accountToken) => {
            const accountUser = await api.getCurrentUser(accountToken);
            return { token: accountToken, user: accountUser };
          })
        );

        const results = settled
          .filter((item): item is PromiseFulfilledResult<Account> => item.status === "fulfilled")
          .map((item) => item.value);

        const validTokens = results.map((account) => account.token);

        if (results.length === 0) {
          throw new Error("No valid saved sessions");
        }

        const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
        if (browserTimezone && browserTimezone !== "UTC") {
          await Promise.allSettled(
            results.map(async (account) => {
              const existingTimezone = account.user?.timezone;
              if (!existingTimezone || existingTimezone === "UTC") {
                await api.updateAccountSettings(account.token, { timezone: browserTimezone });
                account.user = { ...account.user, timezone: browserTimezone };
              }
            })
          );
        }

        setAccounts(results);
        const activeAccount = results.find((account) => account.token === token) || results[0] || null;
        if (activeAccount) {
          setUser(activeAccount.user);
          if (activeAccount.token !== token || validTokens.length !== tokens.length) {
            setToken(activeAccount.token);
            persistTokens(validTokens, activeAccount.token);
          }
        } else {
          setUser(null);
        }

        setError(null);
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : "Failed to fetch user";
        setError(errorMsg);
        setAccounts([]);
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    fetchAccounts();
  }, [token, initialized, tokens]);

  const login = async (loginHint?: string) => {
    try {
      setError(null);
      const loginResponse = await api.getLoginUrl(loginHint);
      if (!loginResponse.authorization_url) {
        throw new Error("No authorization URL returned from server");
      }
      window.location.href = loginResponse.authorization_url;
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "Failed to initiate login";
      setError(errorMsg);
      console.error("Login error details:", err);
    }
  };

  const switchAccount = (nextToken: string) => {
    setToken(nextToken);
    persistTokens(tokens, nextToken);
  };

  const logout = (accountToken?: string) => {
    const targetToken = accountToken || token;
    if (!targetToken) return;

    const updatedTokens = tokens.filter((storedToken) => storedToken !== targetToken);
    const nextActiveToken = targetToken === token ? (updatedTokens[0] || null) : token;

    setTokens(updatedTokens);
    setToken(nextActiveToken);
    persistTokens(updatedTokens, nextActiveToken);

    if (updatedTokens.length === 0) {
      setAccounts([]);
      setUser(null);
    }
  };

  const value = useMemo<AuthContextValue>(() => ({
    token,
    tokens,
    user,
    accounts,
    loading,
    initialized,
    error,
    isAuthenticated: !!token && !!user,
    login,
    logout,
    switchAccount,
  }), [token, tokens, user, accounts, loading, initialized, error]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
