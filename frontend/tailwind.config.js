/** @type {import('tailwindcss').Config} */

// Palette channels live in src/index.css: `:root` (dark) and `[data-theme="light"]`.
// The <alpha-value> placeholder keeps every `bg-canvas/80`-style opacity modifier working.
const token = (name) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: token("--canvas"),
        surface: token("--surface"),
        surfaceMuted: token("--surface-muted"),
        border: token("--border"),
        borderStrong: token("--border-strong"),
        ink: token("--ink"),
        inkMuted: token("--ink-muted"),
        accent: token("--accent"),
        accentStrong: token("--accent-strong"),
        success: token("--success"),
        warning: token("--warning"),
        danger: token("--danger"),
        add: token("--add"),
        del: token("--del"),
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        card: "var(--shadow-card)",
      },
    },
  },
  plugins: [],
};
