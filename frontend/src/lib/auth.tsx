import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type Role = "owner" | "analyst";
export interface SessionUser { username: string; name: string; role: Role; role_label: string }
interface Session { token: string; user: SessionUser }

// Demo accounts (D19). Shown on the sign-in page on purpose: this is a prototype.
export const DEMO_ACCOUNTS: { username: string; password: string; role: Role; title: string; does: string[] }[] = [
  { username: "meera", password: "owner123", role: "owner", title: "Risk owner",
    does: ["Turn worries into fan-pattern rules", "Approve and run rules, compare periods", "Upload new transaction data"] },
  { username: "ravi", password: "analyst123", role: "analyst", title: "Analyst",
    does: ["Work the alert queue", "Investigate alerts with AI-drafted case files", "Dismiss, escalate or ask for more info"] },
];

export const HOME: Record<Role, string> = { owner: "/owner", analyst: "/analyst" };

const KEY = "caselens.session";
let current: Session | null = load();
const listeners = new Set<() => void>();

function load(): Session | null {
  try { const raw = localStorage.getItem(KEY); return raw ? (JSON.parse(raw) as Session) : null; } catch { return null; }
}

function save(s: Session | null) {
  current = s;
  try { if (s) localStorage.setItem(KEY, JSON.stringify(s)); else localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
  listeners.forEach((l) => l());
}

/** Used by the API client for the Authorization header. */
export const getToken = () => current?.token ?? null;
/** Called by the API client on a 401: the session is gone. */
export const endSession = () => { if (current) save(null); };
export const startSession = (s: Session) => save(s);

interface AuthValue { user: SessionUser | null; signOut: () => void }
const Ctx = createContext<AuthValue>({ user: null, signOut: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(current?.user ?? null);
  useEffect(() => {
    const l = () => setUser(current?.user ?? null);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  const signOut = useCallback(() => save(null), []);
  return <Ctx.Provider value={{ user, signOut }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
