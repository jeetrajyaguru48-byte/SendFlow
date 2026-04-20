from fastapi import APIRouter, Header, HTTPException, status

from ..config import settings
from ..email_sender import process_due_campaigns, sync_bounces_and_replies_once

router = APIRouter()


def verify_scheduler_secret(x_scheduler_secret: str = Header(default="")) -> None:
    if not settings.SCHEDULER_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler secret is not configured.",
        )
    if x_scheduler_secret != settings.SCHEDULER_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid scheduler secret.",
        )


@router.post("/scheduler/run")
async def run_scheduler(x_scheduler_secret: str = Header(default="", alias="X-Scheduler-Secret")):
    verify_scheduler_secret(x_scheduler_secret)
    campaign_results = process_due_campaigns()
    return {
        "ok": True,
        "campaigns": campaign_results,
    }


@router.post("/scheduler/inbox-sync")
async def run_inbox_sync(x_scheduler_secret: str = Header(default="", alias="X-Scheduler-Secret")):
    verify_scheduler_secret(x_scheduler_secret)
    inbox_results = sync_bounces_and_replies_once()
    return {
        "ok": True,
        "inbox": inbox_results,
    }
