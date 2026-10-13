/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In dev, the API runs on :8000; in production nginx serves both on one origin.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/healthz": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
  },
});
