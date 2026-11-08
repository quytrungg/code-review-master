/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0b0d12",
        surface: "#12151d",
        surfaceMuted: "#171b25",
        border: "#232838",
        borderStrong: "#2f3650",
        ink: "#e6e9f2",
        inkMuted: "#9aa3bb",
        accent: "#7c8bff",
        accentStrong: "#5b6bfa",
        success: "#3ddc97",
        warning: "#f4c15d",
        danger: "#ff6b81",
        add: "#12351f",
        del: "#3a1520",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.03) inset, 0 10px 30px -20px rgba(0,0,0,0.9)",
      },
    },
  },
  plugins: [],
};
