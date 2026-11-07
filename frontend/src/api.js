const API = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");
export const token = () => localStorage.getItem("mortgage_access_token");
export const session = (d) => {
  localStorage.setItem("mortgage_access_token", d.access_token);
  localStorage.setItem("mortgage_customer", JSON.stringify(d.customer));
};
export const clear = () => {
  localStorage.removeItem("mortgage_access_token");
  localStorage.removeItem("mortgage_customer");
};
export const customer = () => {
  try {
    return JSON.parse(localStorage.getItem("mortgage_customer") || "null");
  } catch {
    return null;
  }
};
export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const accessToken = token();
  const publicAuthPaths = new Set([
    "/auth/login",
    "/auth/register",
    "/auth/verify-otp",
    "/auth/resend-otp",
  ]);
  if (accessToken && !publicAuthPaths.has(path))
    headers.set("Authorization", `Bearer ${accessToken}`);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const r = await fetch(`${API}${path}`, { ...options, headers });
  const ct = r.headers.get("content-type") || "";
  const b = ct.includes("application/json") ? await r.json() : await r.text();
  if (r.status === 401 && !publicAuthPaths.has(path)) {
    clear();
    if (typeof window !== "undefined")
      window.dispatchEvent(new Event("mortgage:session-expired"));
  }
  if (!r.ok) {
    let detail = b?.detail ?? b?.message ?? `Request failed (${r.status})`;
    if (typeof detail !== "string") {
      if (Array.isArray(detail?.errors)) detail = detail.errors.join(" ");
      else if (detail?.message) detail = detail.message;
      else detail = JSON.stringify(detail);
    }
    throw Error(detail);
  }
  return b;
}

export async function download(path, filename) {
  const r = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token()}` },
  });
  if (!r.ok) {
    let m = `Download failed (${r.status})`;
    try {
      m = (await r.json()).detail || m;
    } catch {}
    throw Error(m);
  }
  const u = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = u;
  a.download = filename || "document";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 2000);
}
