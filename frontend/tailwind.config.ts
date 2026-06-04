import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Kalshi-style palette
        surface: {
          DEFAULT: "#0d1117",   // page bg
          1: "#161b22",         // card bg
          2: "#21262d",         // elevated card / input bg
          3: "#30363d",         // borders
        },
        brand: "#6e40c9",       // Kalshi purple-ish accent (we'll use indigo)
        yes: {
          DEFAULT: "#1dc464",   // green
          dim: "#12291e",       // dark green tint
          hover: "#22d66e",
        },
        no: {
          DEFAULT: "#e84040",   // red
          dim: "#2e1212",       // dark red tint
          hover: "#f04f4f",
        },
        muted: "#8b949e",
        subtle: "#6e7681",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      borderColor: {
        DEFAULT: "#30363d",
      },
    },
  },
  plugins: [],
};

export default config;
