# UserLooker

Discord user data extraction and lookup system with rank history tracking, admin dashboard, and data visualization.

## Features

- **User Search** - Look up users by Roblox username or Discord ID
- **Rank History** - Track rank progression with visual timeline
- **Message Viewer** - View user message history with guild/channel context
- **Activity Charts** - Visualize message activity over time
- **Guild Activity** - See message distribution across guilds
- **Admin Dashboard** - Statistics and user management (protected)
- **Discord OAuth** - Secure admin login via Discord
- **Dark/Light Mode** - Theme toggle support
- **Rate Limiting** - API protection with tiered limits

## Requirements

- Python 3.10+
- Node.js 18+
- MongoDB

## Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/BoyAomGame/userlooker.git
cd userlooker
```

### 2. Install Dependencies

**Backend (Python):**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: .\venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

**Frontend (Node.js):**
```bash
cd frontend
npm install
cd ..
```

### 3. Configure Environment

Copy the example and edit with your values:
```bash
cp .env.example .env
```

Key settings in `.env`:
```env
# MongoDB
MONGO_URI=mongodb://localhost:27017
DB_NAME=discord_data

# Discord OAuth2 (for admin login)
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=http://localhost:8001/auth/discord/callback
ADMIN_DISCORD_IDS=your_discord_user_id

# JWT
JWT_SECRET_KEY=your-secret-key-here

# Frontend URL
FRONTEND_URL=http://localhost:5173
```

### 4. Start MongoDB
```bash
# Systemd
sudo systemctl start mongod

# Or Docker
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

### 5. Run the Application

**Backend API (Port 8001):**
```bash
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8001
```

**Frontend (Port 5173):**
```bash
cd frontend
npm run dev
```

Visit http://localhost:5173 to use the app.

## Data Extraction

Extract user data from DiscordChatExporter JSON files:

```bash
# Single file
python extract/dce_extractor.py extract/example.json

# Directory (recursive)
python extract/dce_extractor.py /path/to/json/files/

# From Backblaze B2
python extract/dce_extractor.py --b2 bucket-name prefix/
```

## Updating Dependencies

After pulling new code:
```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

## Production Deployment

### Using PM2 (Recommended)
```bash
# Install PM2
npm install -g pm2

# Start backend
pm2 start "uvicorn main:app --host 0.0.0.0 --port 8001" --name userlooker-api

# Build and serve frontend
cd frontend
npm run build
pm2 serve dist 3000 --name userlooker-frontend --spa

# Save and enable startup
pm2 save
pm2 startup
```

### Environment for Production
```env
FRONTEND_URL=https://yourdomain.com
DISCORD_REDIRECT_URI=https://yourdomain.com/auth/discord/callback
```

## Project Structure

```
userlooker/
├── main.py                 # FastAPI backend entry
├── database.py             # MongoDB connection
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
│
├── routes/                 # API routes
│   ├── auth.py             # Discord OAuth endpoints
│   └── admin.py            # Admin dashboard endpoints
│
├── middleware/             # FastAPI middleware
│   ├── rate_limit.py       # Rate limiting (slowapi)
│   └── audit.py            # Request audit logging
│
├── utils/                  # Utilities
│   ├── auth.py             # JWT authentication
│   ├── pagination.py       # Pagination helpers
│   ├── filters.py          # Search filter builders
│   └── audit.py            # Audit log utilities
│
├── extract/                # Data extraction
│   ├── dce_extractor.py    # DCE JSON parser
│   └── example.json        # Sample data
│
├── RankHistory/
│   └── rank.txt            # Valid ranks list
│
├── briefing/               # Feature documentation
│   ├── Frontend/           # Frontend feature specs
│   ├── API/                # API feature specs
│   └── Backend/            # Backend feature specs
│
└── frontend/               # React + Vite frontend
    ├── src/
    │   ├── components/     # React components
    │   ├── pages/          # Page components
    │   └── context/        # React context providers
    └── package.json
```

## API Endpoints

### Public
- `GET /user/roblox/{username}` - Get user by Roblox username
- `GET /user/discord/{id}` - Get user by Discord ID
- `GET /user/discord/{id}/messages` - Get user messages
- `GET /user/roblox/{username}/rank-history` - Get rank history

### Authentication
- `GET /auth/discord` - Initiate Discord OAuth
- `GET /auth/discord/callback` - OAuth callback
- `POST /auth/logout` - Logout
- `GET /auth/me` - Get current user

### Admin (Protected)
- `GET /admin/statistics` - Dashboard statistics
- `GET /admin/users` - List users with filtering
- `GET /admin/audit-logs` - View audit logs

## Discord OAuth Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create or select an application
3. Go to **OAuth2** → **General**
4. Add redirect URL: `http://localhost:8001/auth/discord/callback`
5. Copy **Client ID** and **Client Secret** to `.env`
6. Get your Discord User ID (Developer Mode → Right-click → Copy ID)
7. Add to `ADMIN_DISCORD_IDS` in `.env`

## License

Private - All rights reserved.
