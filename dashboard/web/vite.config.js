import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = process.env.DASHBOARD_PORT || "8765";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
    },
  },
});
