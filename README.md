# QuickSlateAI

An intelligent sports scheduling platform that combines constraint-based optimization with AI-powered insights.

## Features

- **AI Schedule Generator** — Constraint-optimized season schedules powered by Google OR-Tools CP-SAT solver, with natural language explanations from Claude AI
- **Conflict Dashboard** — Real-time constraint validation with drag-and-drop rescheduling and undo support
- **Travel Optimizer** — Team travel analysis with interactive Leaflet maps, fairness scoring, and hotel grouping suggestions
- **Audience Estimator** — Viewership projections based on timeslot, rivalry status, and market factors, visualized with D3.js
- **Tournament Bracket Generator** — Automated brackets (single/double elimination, round-robin, pool play) with field rotation fairness

## Tech Stack

React 18 · TypeScript · Tailwind CSS · D3.js · Leaflet.js · FastAPI · Google OR-Tools · Claude API (claude-sonnet-4-6) · Docker

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # Add your ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

API runs at http://localhost:8000 · Docs at http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App runs at http://localhost:5173

### Docker (full stack)

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and add ANTHROPIC_API_KEY
docker-compose up --build
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key for AI explanations | (mock mode if absent) |
| `DATABASE_URL` | PostgreSQL URL | SQLite in dev |
| `ALLOWED_ORIGINS` | CORS allowed origins | `http://localhost:5173` |

> **Note:** The app works without an Anthropic API key — AI explanations fall back to smart template-based text.

## Leagues & Teams

### National Pro League (NPL)
Cary Cobras · Charlotte Thunder · Raleigh Hawks · Durham Blaze · Asheville Storms · Greensboro Wolves · Wilmington Tide · Fayetteville Falcons

### Southern Athletic Conference (SAC)
Riverside Lions · Lakewood Bears · Oakridge Stallions · Pinehurst Eagles · Brookside Panthers · Westgate Titans · Eastfield Sharks · Northview Knights

All teams, venues, and data are fictional and synthetically generated.

## Deployment

- **Frontend**: Deploy the `frontend/` folder to [Vercel](https://vercel.com) — set `VITE_API_URL` to your backend URL
- **Backend**: Deploy to [Railway](https://railway.app) or [Render](https://render.com) using the `Dockerfile`

---

Built by Harsha Kanaparthi · [Portfolio](https://harshakanaparthi.me) · [GitHub](https://github.com/HKanaparthi) · [LinkedIn](https://linkedin.com/in/harsha2003)
