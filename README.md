# 🚗 Remote Vehicle Control over Internet (PoC)

## 📌 Project Description
This project is a **Proof of Concept (PoC)** for controlling a vehicle remotely over the Internet using:
- a **central server**
- **camera video streaming**
- an **ESP32 microcontroller for servo control**
- **UART communication between SBC and ESP32**

The system is designed so that the **phone or web browser never connects directly to the vehicle**.  
All communication goes through a **server**, enabling:
- remote control over the Internet (NAT / LTE / CGNAT friendly)
- better scalability
- improved security

The project serves as a **foundation for further development**, such as RC vehicles, mobile robots, or autonomous platforms.

---

## 🧠 System Architecture

[ Phone / Web UI ]
|
v
[ Server (API / WebSocket) ]
|
v
[ SBC (Raspberry Pi / Radxa) ]
|
UART
|
v
[ ESP32 ] ---> [ Servo ]


### 🔹 Component Responsibilities
- **Phone / Web UI** – user interface (buttons, joystick, video preview)
- **Server** – communication hub between client and vehicle
- **SBC (Raspberry Pi / Radxa)**  
  - receives commands from the server  
  - sends control data to ESP32 via UART  
  - streams video from the camera
- **ESP32** – low-level servo control using PWM

---

## 🎯 Project Goals (PoC)
- ✅ Remote servo control over the Internet
- ✅ Separation of UI, server, and hardware control layers
- ✅ Low-latency communication
- ✅ Ready for LTE / mobile Internet
- ⏳ Multi-channel control
- ⏳ Support for multiple vehicles

---

## 🧩 Repository Structure


---

## 📂 Directory & File Overview

### 🔹 `/server`
Server-side application acting as a communication bridge.

- **app.py**  
  Main server application handling connections from clients and SBCs.
- **requirements.txt**  
  Python dependencies required to run the server.
- **README.md**  
  Detailed server setup and configuration instructions.

---

### 🔹 `/sbc`
Software running on Raspberry Pi or Radxa SBC.

- **uart_client.py**  
  Handles UART communication with the ESP32.
- **camera_stream.py**  
  Captures and streams video from the connected camera.
- **config.py**  
  Configuration file (ports, IP addresses, UART parameters).

---

### �� `/esp32`
ESP32 firmware.

- **main.ino**  
  Main ESP32 program receiving commands and controlling the servo.
- **servo_control.h**  
  Servo control logic using PWM.

---

### 🔹 `/webui`
Web-based user interface.

- **index.html** – UI structure
- **script.js** – control logic (buttons, joystick, communication)
- **style.css** – UI styling

---

### 🔹 `/diagrams`
- **architecture.png** – system architecture diagram

---

## ⚙️ Hardware Requirements
- Raspberry Pi or Radxa (target platform: Radxa Cubie A7Z)
- ESP32
- Servo motor (PWM controlled)
- Camera (CSI or USB)
- Internet connection (WiFi / LTE)

---

## 🚀 Possible Extensions
- Multi-servo support
- DC motor / ESC control
- User authentication
- Video recording
- Autonomous driving modes
- Mobile application

---

## 🧪 Project Status
**Proof of Concept – under active development**

---

## 📄 License
To be defined.

