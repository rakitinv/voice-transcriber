import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

// Vite configuration (skeleton).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173
  }
});

