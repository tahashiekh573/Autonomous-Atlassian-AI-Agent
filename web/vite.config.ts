import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// /api and /health are proxied to the backend so the browser talks to one origin (no CORS, no
// backend URL baked into the bundle). Override the target with API_URL, e.g.
//   API_URL=http://localhost:8765 npm run dev
export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, ".", "").API_URL || "http://localhost:8000";
  const proxy = { "/api": target, "/health": target };
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { proxy },
  };
});
