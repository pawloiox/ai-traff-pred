import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Poboczny projekt podglądu UI — Vite + React + Tailwind v4.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    open: true,
    // Podglad pobiera zywe dane z backendu FastAPI (uvicorn :8000).
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
