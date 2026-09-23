import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Local default binds privately; remote access goes through authentication (Supabase JWT).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
});
