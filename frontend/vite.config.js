import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Poboczny projekt podglądu UI — Vite + React + Tailwind v4.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    open: true,
  },
});
