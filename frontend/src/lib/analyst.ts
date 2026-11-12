import { useEffect, useState } from "react";

// The analyst name is a UI preference stored in localStorage (no auth in the prototype).
const KEY = "caselens.analyst";
const EVENT = "caselens-analyst";

function read(): string {
  try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; }
}

export function useAnalyst(): [string, (v: string) => void] {
  const [name, setName] = useState(read);
  useEffect(() => {
    const sync = () => setName(read());
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);
  const set = (v: string) => {
    try { localStorage.setItem(KEY, v); } catch { /* storage unavailable */ }
    setName(v);
    window.dispatchEvent(new Event(EVENT));
  };
  return [name, set];
}
