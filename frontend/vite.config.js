import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "fs";
import path from "path";

import { cloudflare } from "@cloudflare/vite-plugin";

function legalArtifacts() {
  const sourceDirectory = process.env.DAEMONSTATE_LEGAL_DIR
    ? path.resolve(process.env.DAEMONSTATE_LEGAL_DIR)
    : path.resolve(process.cwd(), "..");
  const files = ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt"];
  let resolvedConfig;

  return {
    name: "daemonstate-legal-artifacts",
    configResolved(config) {
      resolvedConfig = config;
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const filename = request.url?.replace(/^\/assets\/legal\//, "");
        if (!filename || !files.includes(filename)) {
          next();
          return;
        }
        response.setHeader("content-type", "text/plain; charset=utf-8");
        response.end(fs.readFileSync(path.join(sourceDirectory, filename)));
      });
    },
    closeBundle() {
      const destination = path.resolve(
        resolvedConfig.root,
        resolvedConfig.build.outDir,
        "assets",
        "legal",
      );
      fs.mkdirSync(destination, { recursive: true });
      for (const filename of files) {
        fs.copyFileSync(
          path.join(sourceDirectory, filename),
          path.join(destination, filename),
        );
      }
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    legalArtifacts(),
    ...(mode === "test" ? [] : [cloudflare()]),
  ],
  resolve: {
    alias: {
      "@assets": path.resolve(__dirname, "src/assets"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    css: false,
  },
  server: {
    // The dev proxy reaches local-only API actions, so it must not turn a
    // loopback backend into a LAN-accessible service.
    host: "127.0.0.1",
    port: 5000,
    allowedHosts: ["localhost", "127.0.0.1"],
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
}));
