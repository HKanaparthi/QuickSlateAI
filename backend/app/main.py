import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from .routes import schedule, travel, audience, tournament

app = FastAPI(
    title="QuickSlateAI API",
    description="Intelligent sports scheduling platform with constraint optimization and AI insights",
    version="1.0.0",
)

origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in origins else origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(schedule.router)
app.include_router(travel.router)
app.include_router(audience.router)
app.include_router(tournament.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "QuickSlateAI API"}


@app.get("/")
def root():
    return {
        "name": "QuickSlateAI API",
        "docs": "/docs",
        "health": "/health",
    }
