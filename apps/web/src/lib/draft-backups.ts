/** Local-only recovery. Embedded authenticated Studio never persists customer graphs. */
function storage(): Storage | undefined {
  const root = process.env.NEXT_PUBLIC_STUDIO_EMBED_ROOT;
  if (typeof window === "undefined" || root && window.location.pathname.startsWith(root)) return undefined;
  return window.localStorage;
}
export const draftBackups = {
  getItem(key: string) { return storage()?.getItem(key) ?? null; },
  setItem(key: string, value: string) { storage()?.setItem(key, value); },
  removeItem(key: string) { storage()?.removeItem(key); },
};
