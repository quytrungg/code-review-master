export type Theme = "dark" | "light";

const STORAGE_KEY = "theme";

/**
 * The whole state space is one attribute on <html>: absent means dark (the original theme).
 * The preference is a browser-local cosmetic choice, so it lives in localStorage — not in the
 * account settings on the server.
 */
export function getTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function setTheme(theme: Theme) {
  if (theme === "light") {
    document.documentElement.dataset.theme = "light";
  } else {
    delete document.documentElement.dataset.theme;
  }
  window.localStorage.setItem(STORAGE_KEY, theme);
}

export function toggleTheme(): Theme {
  const next = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

/** Apply the saved choice before first paint, so a reload never flashes the other theme. */
export function initTheme() {
  if (window.localStorage.getItem(STORAGE_KEY) === "light") {
    document.documentElement.dataset.theme = "light";
  }
}
