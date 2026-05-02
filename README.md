# WhatsApp Multi-Session Gateway PRO

A high-performance WhatsApp Gateway built with **FastAPI** and **Neonize**, supporting multiple accounts, complex messaging types, and a comprehensive management dashboard.

## 🚀 Key Features

### 📱 Multi-Session Management
- **Add Multiple Accounts**: Connect and manage multiple WhatsApp numbers simultaneously.
- **Pairing Code**: Login easily using pairing codes (no QR scan required in UI).
- **Session Persistence**: Sessions are saved and automatically restored on restart.
- **Device Management**: Monitor connection status and logout devices remotely.

### 📩 Comprehensive API (GET & POST Support)
- **Text Messaging**: Send plain text messages to individuals or groups.
- **Media Support**:
  - `send-image`: Send images with captions.
  - `send-audio`: Send audio files or voice notes.
  - `send-video`: Send videos.
  - `send-document`: Send any file type as a document.
  - `send-sticker`: Send WebP stickers.
- **Advanced Messaging**:
  - `send-contact`: Send VCards.
  - `send-interactive`: Send interactive native flow buttons and lists.
  - `send-status`: Post text or media updates to WhatsApp Status.
- **Utility Endpoints**:
  - `check-number`: Verify if a phone number is registered on WhatsApp.
  - `convert-jid`: Convert phone numbers to WhatsApp JIDs.
  - `groups`: List all joined groups.
  - `group-info`: Get detailed information and member lists of a group.

### 📊 Web Dashboard
- **Statistics**: View total users and active bot connections.
- **Blast Messaging**: Send broadcast messages to multiple recipients from the UI.
- **Logs Viewer**: Real-time tracking of incoming and outgoing message activities.
- **Tools**: Integrated tools for JID conversion and number checking.
- **User Management**: Registration, login, and secure API Key generation.

### 🛡️ Security & Reliability
- **API Key Auth**: Every external request must be authenticated with a unique user API key.
- **Host Restriction**: Access to internal web routes is restricted to authorized domains.
- **Session Middleware**: Secure session handling for the web interface.
- **Asynchronous Core**: Built on `asyncio` for non-blocking performance.

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.10+)
- **WhatsApp Engine**: [Neonize](https://github.com/krypton-byte/neonize) (based on whatsmeow)
- **Database**: SQLite with `aiosqlite` for asynchronous DB operations.
- **UI**: HTML5, Bootstrap 5, Plus Jakarta Sans.

## 📦 Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Nauvalunesa/Wa-gateway.git
   cd wa-gateway
   ```

2. **Create and activate a virtual environment (recommended)**:
  ```bash
  python -m venv .venv
  # PowerShell
  .\.venv\Scripts\Activate.ps1
  # CMD
  .venv\Scripts\activate.bat
  ```

3. **Install dependencies**:
  ```bash
  python -m pip install -r requirements.txt
  ```

4. **Run the application**:
  ```bash
  python main.py
  ```
  If you do not activate the virtual environment, run:
  ```bash
  .\.venv\Scripts\python.exe main.py
  ```
  Default dashboard URL: `http://localhost:8880`

## 📖 API Usage Example

**Send a Text Message:**
```bash
GET /api/send-message?number=628123456789&text=Hello&key=YOUR_API_KEY
```

**Check Number:**
```bash
GET /api/check-number?number=628123456789&key=YOUR_API_KEY
```

## 📂 Project Structure

- `main.py`: Core FastAPI application and API logic.
- `serialize.py`: Advanced message serialization for Neonize.
- `msg_store.py`: Message tracking for interactive responses.
- `templates/`: Full suite of dashboard HTML templates.
- `storage/`: Persistent system and user data.

## 📜 License
MIT License.
