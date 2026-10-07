// API client — talks to the Django backend, OR to pre-baked static JSON (Phase-1 static demo).
// Same call sites either way; set NEXT_PUBLIC_STATIC=1 + NEXT_PUBLIC_API_URL=/data-static/api for static.
// default is the relative "/api" — next.config.ts proxies it to the Django backend, so it works both
// locally AND through a share tunnel (same origin, no CORS). Override via NEXT_PUBLIC_API_URL if needed.
export const API = process.env.NEXT_PUBLIC_API_URL ?? "/api";
const STATIC = process.env.NEXT_PUBLIC_STATIC === "1";

// all orderings of the query params — the export baked one fixed order (e.g. unit&demo), but call sites
// don't always match it (e.g. demo&unit), so we try every permutation before giving up.
function permute(arr: string[]): string[][] {
  if (arr.length <= 1) return [arr];
  if (arr.length > 4) return [arr]; // export uses <=3 params; don't explode on anything larger
  const out: string[][] = [];
  arr.forEach((x, i) => {
    for (const rest of permute([...arr.slice(0, i), ...arr.slice(i + 1)])) out.push([x, ...rest]);
  });
  return out;
}

// list params that only narrow/paginate results — the static build didn't bake every combo (e.g. unit+page),
// so if no exact file exists we drop these and fall back to the broader baked list (unit-filtered, or full).
const DROPPABLE = ["search", "flag", "page"];

// candidate pre-baked files for an API path, tolerant to query-param ORDER and to un-baked narrow/page combos:
// "/items?page=1&unit=211" -> [..."items__page=1__unit=211.json", ...(drop page)..."items__unit=211.json", "items.json", "items__page=1.json"]
function staticCandidates(path: string): string[] {
  const [p, q = ""] = path.split("?");
  const base = `${API}${p.replace(/\/+$/, "")}`;
  const urls = new Set<string>();
  const addPerms = (arr: string[]) => {
    if (arr.length) for (const order of permute(arr)) urls.add(`${base}__${order.join("__")}.json`);
  };
  if (q) {
    const parts = q.split("&").filter(Boolean);
    addPerms(parts);                                   // exact params, any order
    let cur = parts;
    for (const key of DROPPABLE) {                     // progressively drop search, then flag, then page
      const next = cur.filter((x) => x.split("=")[0] !== key);
      if (next.length !== cur.length) { addPerms(next); cur = next; }
    }
  }
  urls.add(`${base}.json`);            // unfiltered list
  urls.add(`${base}__page=1.json`);   // ...or its baked first page
  return [...urls];
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("akij_token");
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem("akij_token", t);
  else localStorage.removeItem("akij_token");
}

export function getUsername(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("akij_user");
}

export async function apiGet<T>(path: string): Promise<T> {
  if (STATIC) {
    // try every param ordering, then the query-stripped base, before giving up
    for (const url of staticCandidates(path)) {
      const r = await fetch(url);
      if (r.ok) return r.json();
    }
    throw new Error(`static: no pre-baked file for ${path}`);
  }
  const headers: Record<string, string> = {};
  const tok = getToken();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const r = await fetch(`${API}${path}`, { headers, cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`);
  return r.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const tok = getToken();
  if (tok) headers["Authorization"] = `Token ${tok}`;
  const r = await fetch(`${API}${path}`, {
    method: "POST", headers, body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`${r.status}: ${detail.slice(0, 200)}`);
  }
  return r.json();
}

export async function login(username: string, password: string): Promise<void> {
  const r = await fetch(`${API}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw new Error("Invalid username or password");
  const { token } = await r.json();
  setToken(token);
  localStorage.setItem("akij_user", username);
}

export function logout() {
  setToken(null);
  localStorage.removeItem("akij_user");
}

// ---- shared formatting ----
export const fmt = (v: number | null | undefined, digits = 0): string =>
  v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: digits });

export const fmtM = (v: number | null | undefined): string =>
  v == null ? "—" : `${(v / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
