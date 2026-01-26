const express = require("express");
const http = require("http");

// Cloudflare Realtime (Calls) credentials z ENV
const CF_APP_ID = process.env.CF_REALTIME_APP_ID || "";
const CF_TOKEN = process.env.CF_REALTIME_TOKEN || "";

const app = express();
app.use(express.static("public"));
app.use(express.json()); // ADD THIS for JSON body parsing

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

// Proxy endpoint for browser to join session
app.post("/api/join-session", async (req, res) => {
  const { sessionId, offer } = req.body;
  
  if (!sessionId || !offer) {
    return res.status(400).json({ error: "Missing sessionId or offer" });
  }
  
  if (!CF_APP_ID || !CF_TOKEN) {
    return res.status(500).json({ error: "Server not configured with Cloudflare credentials" });
  }
  
  try {
    const fetch = (await import('node-fetch')).default;
    
    // Create new pull track on existing session
    // Pull the "car-video" track from the car's session
    const url = `https://rtc.live.cloudflare.com/v1/apps/${CF_APP_ID}/sessions/${sessionId}/tracks/new`;
    
    const payload = {
      sessionDescription: offer,
      tracks: [{
        location: 'remote',
        trackName: 'car-video',  // Pull the named track from car
        sessionId: sessionId
      }]
    };
    
    console.log('[PROXY] Creating pull track for car-video...');
    console.log('[PROXY] Session ID:', sessionId);
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${CF_TOKEN}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
    
    const responseText = await response.text();
    console.log('[PROXY] Cloudflare response status:', response.status);
    
    if (!response.ok) {
      console.error('[PROXY] Cloudflare error:', responseText);
      return res.status(response.status).json({ error: responseText });
    }
    
    const data = JSON.parse(responseText);
    console.log('[PROXY] Successfully created pull track');
    
    // Check if track was found
    if (data.tracks && data.tracks[0] && data.tracks[0].errorCode) {
      const trackError = data.tracks[0];
      console.error('[PROXY] Track error:', trackError.errorDescription);
      return res.status(404).json({ 
        error: `Track error: ${trackError.errorDescription}. Make sure car is connected and streaming.` 
      });
    }
    
    res.json({ answer: data.sessionDescription });
    
  } catch (error) {
    console.error('[PROXY] Error:', error);
    res.status(500).json({ error: error.message });
  }
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
