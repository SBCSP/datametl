// Bearer-token storage for the simple in-app login. The token is kept in localStorage and
// attached as `Authorization: Bearer` by the API client. Login/logout do a full page reload so
// the whole app (and the auth gate) re-initializes with the new state.

const KEY = "datametl_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function setToken(token: string): void {
  if (typeof window !== "undefined") window.localStorage.setItem(KEY, token);
}

export function clearToken(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}
