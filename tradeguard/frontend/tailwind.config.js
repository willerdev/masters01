/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["IBM Plex Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      colors: {
        ink: "var(--ink)",
        panel: "var(--panel)",
        line: "var(--line)",
        muted: "var(--muted)",
        accent: "var(--accent)",
        profit: "var(--profit)",
        loss: "var(--loss)",
        warn: "var(--warn)",
      },
    },
  },
  plugins: [],
};
