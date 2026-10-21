import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Same-origin API in dev, exactly like production: strict cookies, no CORS.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (id.includes("recharts") || id.includes("d3-")) return "charts";
          if (id.includes("motion")) return "motion";
          if (id.includes("node_modules")) return "vendor";
        },
      },
    },
  },
});
