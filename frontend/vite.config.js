import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Vite + React + Tailwind v4.
// Build trafia do app/static/spa i jest serwowany przez FastAPI pod /app
// (asset paths z base /static/spa/). Dev: proxy /api -> backend :8000.
export default defineConfig(({ command }) => ({
  // build: serwowany przez FastAPI pod /static/spa; dev: root (podglad :5174/)
  base: command === "build" ? "/static/spa/" : "/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../app/static/spa",
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    open: true,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
}));
