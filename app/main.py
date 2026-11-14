from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db


app = FastAPI(
    title="EventSphere",
    description="Agent-Based Venue Booking and Digital Ticketing Platform",
    version="1.0.0"
)


@app.get("/")
def home():
    return {
        "message": "Welcome to EventSphere!",
        "project": "IT4123 ICA 02",
        "status": "Backend is running successfully"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "EventSphere"
    }


@app.get("/db-check")
def check_database(db: Session = Depends(get_db)):
    try:
        result = db.execute(
            text("SELECT current_database()")
        ).scalar_one()

        return {
            "status": "connected",
            "database": result,
            "message": "PostgreSQL connection successful"
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed"
        )