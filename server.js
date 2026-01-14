const express = require("express");
const http = require("http");
const WebSocket = require("ws");
const crypto = require("crypto");

const app = express();
app.use(express.static("public"));

const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

const rooms = new Map(); // roomId -> { car: ws|null, ui: ws|null }

function rid() {
  return crypto.randomBytes(4).toString("hex");
}

wss.on("connection", (ws) => {
  ws.id = rid();
  ws.roomId = null;
  ws.role = null;

  console.log(`[WS] connect id=${ws.id}`);

  ws.on("message", (msg) => {
    let data;
    try { data = JSON.parse(msg.toString()); } catch { return; }

    if (data.type === "join") {
      const roomId = data.roomId;
      const role = data.role; // "car" albo "ui"
      if (!roomId || (role !== "car" && role !== "ui")) {
        ws.send(JSON.stringify({ type: "error", error: "join requires {roomId, role:'car'|'ui'}" }));
        return;
      }

      ws.roomId = roomId;
      ws.role = role;

      if (!rooms.has(roomId)) rooms.set(roomId, { car: null, ui: null });
      const room = rooms.get(roomId);

      // tylko 1 car i 1 ui
      if (room[role] && room[role].readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "error", error: `role ${role} already connected` }));
        ws.close();
        return;
      }

      room[role] = ws;

      console.log(`[WS] join room=${roomId} role=${role} id=${ws.id}`);
      ws.send(JSON.stringify({ type: "joined", roomId, role, id: ws.id }));
      return;
    }

    if (!ws.roomId || !ws.role) return;

    const room = rooms.get(ws.roomId);
    if (!room) return;

    // route tylko do drugiej roli
    const target = ws.role === "car" ? room.ui : room.car;
    if (target && target.readyState === WebSocket.OPEN) {
      target.send(JSON.stringify(data));
    } else {
      // pomocne w debug
      // console.log(`[WS] drop type=${data.type} room=${ws.roomId} no target`);
    }
  });

  ws.on("close", () => {
    console.log(`[WS] close id=${ws.id} room=${ws.roomId} role=${ws.role}`);
    if (ws.roomId && rooms.has(ws.roomId)) {
      const room = rooms.get(ws.roomId);
      if (room.car === ws) room.car = null;
      if (room.ui === ws) room.ui = null;
      if (!room.car && !room.ui) rooms.delete(ws.roomId);
    }
  });
});

server.listen(8080, "127.0.0.1", () => {
  console.log("HTTP+WS on :8080");
});
