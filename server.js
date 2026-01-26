const express = require("express");
const http = require("http");

// Cloudflare Realtime (Calls) credentials z ENV
const CF_APP_ID = process.env.CF_REALTIME_APP_ID || "";
const CF_TOKEN = process.env.CF_REALTIME_TOKEN || "";

const app = express();
app.use(express.static("public"));

// Endpoint do pobrania konfiguracji Cloudflare
app.get("/config", (_req, res) => {
  res.json({
    appId: CF_APP_ID,
    token: CF_TOKEN ? "use-from-env" : "",
    hasToken: !!CF_TOKEN,
  });
});

// Health check endpoint
app.get("/health", (_req, res) => {
  res.json({ 
    status: "ok", 
    mode: "cloudflare-sfu",
    cfConfigured: !!(CF_APP_ID && CF_TOKEN)
  });
});

const server = http.createServer(app);

// WebSocket signaling is no longer needed - Cloudflare handles all WebRTC signaling
// Browser connects directly to Cloudflare Realtime API
// Car publishes to Cloudflare via REST API

server.listen(8080, "127.0.0.1", () => {
  console.log("[SERVER] HTTP server on :8080");
  console.log("[SERVER] Mode: Cloudflare Realtime SFU");
  console.log("[SERVER] No WebSocket signaling needed - using Cloudflare API");
  
  if (!CF_APP_ID || !CF_TOKEN) {
    console.warn("[SERVER] WARNING: CF_REALTIME_APP_ID or CF_REALTIME_TOKEN not set!");
    console.warn("[SERVER] Set environment variables for Cloudflare integration");
  } else {
    console.log("[SERVER] Cloudflare credentials configured");
  }
});
