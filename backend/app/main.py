from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
from sqlalchemy import func

from app.config import settings
from app.database import create_tables
from app.database import SessionLocal
from app.models import Campaign, Lead
from app.routers import auth, campaigns, analytics, sequences
from app.routers import inbox, internal, unsubscribe
from app.tracking import get_tracking_pixel, track_link_click
from migrate import migrate_database


def recover_orphaned_campaigns() -> None:
    """Reset transient in-progress statuses on startup."""
    db = SessionLocal()
    try:
        running_campaigns = db.query(Campaign).filter(Campaign.status.in_(["running", "queued"])).all()
        for campaign in running_campaigns:
            pending_leads = db.query(func.count(Lead.id)).filter(
                Lead.campaign_id == campaign.id,
                Lead.status == "pending",
                Lead.opted_out.is_(False)
            ).scalar() or 0
            campaign.status = "scheduled" if pending_leads > 0 else "completed"
            if campaign.status == "completed":
                campaign.next_send_at = None
        db.commit()
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_tables()
    migrate_database()
    recover_orphaned_campaigns()
    yield
    # Shutdown

app = FastAPI(
    title="Email Automation API",
    description="API for email automation with Gmail integration",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["Campaigns"])
app.include_router(sequences.router, prefix="/sequences", tags=["Sequences"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(inbox.router, prefix="/inbox", tags=["Inbox"])
app.include_router(internal.router, prefix="/internal", tags=["Internal"])
app.include_router(unsubscribe.router, tags=["Unsubscribe"])

# Tracking endpoints (public, no auth required)
@app.get("/track/pixel/{tracking_id}")
async def track_pixel(tracking_id: str):
    """Serve tracking pixel for email opens."""
    return get_tracking_pixel(tracking_id)

@app.get("/track/click/{tracking_id}")
async def track_click(tracking_id: str, url: str):
    """Track link clicks and redirect."""
    redirect_url = track_link_click(tracking_id, url)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=redirect_url)

@app.get("/")
async def root():
    return {"message": "Email Automation API", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
