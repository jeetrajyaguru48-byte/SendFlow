from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import pytz

from ..database import get_db
from ..auth import get_current_user
from ..models import Campaign, Lead, EmailLog, DailySendLog
from ..schemas import CampaignStats, LeadStatus


def _last_lead_event(lead: Lead):
    events = [
        ("replied", lead.replied_at),
        ("clicked", lead.clicked_at),
        ("read", lead.read_at),
        ("bounced", lead.bounced_at),
        ("sent", lead.sent_at),
    ]
    valid_events = [event for event in events if event[1] is not None]
    if not valid_events:
        return None, None
    return max(valid_events, key=lambda item: item[1])

router = APIRouter()

def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)

def calculate_next_send_time(campaign: Campaign, lead: Lead, user_timezone: str = "UTC", daily_sends: int = 0, daily_limit: int = 30) -> Tuple[Optional[datetime], str]:
    """
    Calculate when the next email will be sent to this lead.
    Returns (next_send_time, status_description)
    """
    # If campaign is not running, no next send
    if campaign.status not in ['running', 'active']:
        return None, "Campaign not running"

    # If lead has opted out, no next send
    if lead.opted_out:
        return None, "Lead opted out"

    # If lead has already been sent to and campaign is one-time, no next send
    if lead.sent_at and not campaign.is_sequence:
        return None, "Email already sent"

    # If lead is in a sequence, check sequence enrollment
    if campaign.is_sequence and hasattr(lead, 'sequence_enrollments'):
        enrollment = lead.sequence_enrollments[0] if lead.sequence_enrollments else None
        if enrollment and enrollment.next_send_at:
            return enrollment.next_send_at, "Next sequence email"

    # For regular campaigns, calculate based on send window and delays
    now = datetime.now(pytz.UTC)
    campaign_start_time = ensure_utc(campaign.send_start_time)
    lead_sent_at = ensure_utc(lead.sent_at)

    # If this is the first send and campaign has a start time
    if not lead_sent_at and campaign_start_time:
        if campaign_start_time > now:
            return campaign_start_time, "Campaign scheduled to start"

    # Get the last sent time (either lead.sent_at or campaign start time)
    last_sent = lead_sent_at or campaign_start_time or now

    # Calculate delay
    min_delay = campaign.min_delay_minutes or 2
    max_delay = campaign.max_delay_minutes or 7
    # For simplicity, use average delay for estimation
    avg_delay_minutes = (min_delay + max_delay) / 2
    next_send = last_sent + timedelta(minutes=avg_delay_minutes)

    # Apply send window constraints
    if campaign.send_window_start and campaign.send_window_end:
        # Parse send window times
        try:
            window_start_hour = int(campaign.send_window_start.split(':')[0])
            window_end_hour = int(campaign.send_window_end.split(':')[0])

            # Convert to user's timezone for calculation
            user_tz = pytz.timezone(user_timezone)
            next_send_local = next_send.astimezone(user_tz)

            # If next_send is outside window, move to next valid window
            current_hour = next_send_local.hour

            if current_hour < window_start_hour:
                # Too early, move to start of window today
                next_send_local = next_send_local.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)
            elif current_hour >= window_end_hour:
                # Too late, move to start of window tomorrow
                next_send_local = next_send_local.replace(hour=window_start_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)

            # Handle weekdays only
            if campaign.send_window_weekdays_only:
                while next_send_local.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    next_send_local += timedelta(days=1)
                    next_send_local = next_send_local.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)

            next_send = next_send_local.astimezone(pytz.UTC)
        except (ValueError, IndexError):
            pass  # Invalid time format, skip window logic

    # Check daily limits
    if daily_sends >= daily_limit:
        # Daily limit reached, schedule for tomorrow
        tomorrow = now + timedelta(days=1)
        tomorrow = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)  # Default 9 AM
        return tomorrow, "Daily limit reached"

    # If next_send is in the past, it means it should be sent soon
    if next_send <= now:
        return now, "Sending soon"
    else:
        return next_send, "Scheduled"


def _get_recent_email_history_by_lead(db: Session, lead_ids: List[int]) -> dict[int, List[dict]]:
    if not lead_ids:
        return {}

    ranked_logs = (
        db.query(
            EmailLog.lead_id.label("lead_id"),
            EmailLog.timestamp.label("timestamp"),
            EmailLog.status.label("status"),
            EmailLog.subject.label("subject"),
            EmailLog.error_message.label("error_message"),
            EmailLog.variant.label("variant"),
            func.row_number().over(
                partition_by=EmailLog.lead_id,
                order_by=EmailLog.timestamp.desc(),
            ).label("rank"),
        )
        .filter(EmailLog.lead_id.in_(lead_ids))
        .subquery()
    )

    recent_logs = (
        db.query(ranked_logs)
        .filter(ranked_logs.c.rank <= 10)
        .order_by(ranked_logs.c.lead_id, ranked_logs.c.timestamp.desc())
        .all()
    )

    history_by_lead: dict[int, List[dict]] = defaultdict(list)
    for log in recent_logs:
        history_by_lead[log.lead_id].append(
            {
                "timestamp": log.timestamp,
                "status": log.status,
                "subject": log.subject,
                "error_message": log.error_message,
                "variant": log.variant,
            }
        )

    return history_by_lead

@router.get("/campaign/{campaign_id}/stats", response_model=CampaignStats)
async def get_campaign_stats(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get statistics for a campaign."""
    # Verify campaign ownership
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.user_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get lead counts by status
    status_counts = db.query(
        Lead.status,
        func.count(Lead.id)
    ).filter(Lead.campaign_id == campaign_id).group_by(Lead.status).all()

    stats = {status: count for status, count in status_counts}

    return CampaignStats(
        total_leads=sum(stats.values()),
        sent=stats.get('sent', 0),
        read=stats.get('read', 0),
        clicked=stats.get('clicked', 0),
        bounced=stats.get('bounced', 0),
        replied=stats.get('replied', 0)
    )

@router.get("/campaign/{campaign_id}/leads", response_model=List[LeadStatus])
async def get_campaign_leads(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get all leads for a campaign with their status."""
    # Verify campaign ownership
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.user_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get all leads for this campaign
    leads = db.query(Lead).filter(Lead.campaign_id == campaign_id).all()
    lead_ids = [lead.id for lead in leads]
    history_by_lead = _get_recent_email_history_by_lead(db, lead_ids)

    # Get daily send count for the user
    today = datetime.now(pytz.UTC).date()
    daily_sends_count = db.query(func.count(EmailLog.id)).filter(
        EmailLog.user_id == current_user.id,
        func.date(EmailLog.timestamp) == today
    ).scalar() or 0

    result = []
    for lead in leads:
        next_send_time, send_status = calculate_next_send_time(
            campaign, 
            lead, 
            current_user.timezone or "UTC",
            daily_sends_count,
            current_user.daily_limit or 30
        )
        last_event_type, last_event_at = _last_lead_event(lead)

        result.append(LeadStatus(
            id=lead.id,
            email=lead.email,
            name=lead.name,
            status=lead.status,
            company=lead.company,
            title=lead.title,
            phone=lead.phone,
            website=lead.website,
            linkedin_url=lead.linkedin_url,
            location=lead.location,
            source=lead.source,
            notes=lead.notes,
            custom_fields=lead.custom_fields,
            priority=lead.priority,
            reply_category=lead.reply_category,
            last_contacted_at=lead.last_contacted_at,
            opted_out=lead.opted_out,
            lifecycle_stage=lead.lifecycle_stage or "new",
            lead_score=lead.lead_score or 0,
            needs_follow_up=lead.needs_follow_up,
            converted_at=lead.converted_at,
            sent_at=lead.sent_at,
            read_at=lead.read_at,
            clicked_at=lead.clicked_at,
            bounced_at=lead.bounced_at,
            replied_at=lead.replied_at,
            next_send_at=next_send_time,
            send_status=send_status,
            last_event_type=last_event_type,
            last_event_at=last_event_at,
            email_history=history_by_lead.get(lead.id, []),
        ))

    return result

@router.get("/dashboard")
async def get_dashboard_data(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get dashboard data for current user."""
    # Get all campaigns
    campaigns = db.query(Campaign).filter(Campaign.user_id == current_user.id).all()

    dashboard_data = []
    for campaign in campaigns:
        # Get stats for each campaign
        status_counts = db.query(
            Lead.status,
            func.count(Lead.id)
        ).filter(Lead.campaign_id == campaign.id).group_by(Lead.status).all()

        stats = {status: count for status, count in status_counts}

        dashboard_data.append({
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "status": campaign.status,
            "created_at": campaign.created_at,
            "stats": {
                "total_leads": sum(stats.values()),
                "sent": stats.get('sent', 0),
                "read": stats.get('read', 0),
                "clicked": stats.get('clicked', 0),
                "bounced": stats.get('bounced', 0),
                "replied": stats.get('replied', 0)
            }
        })

    return {"campaigns": dashboard_data}


@router.get("/overview")
async def get_analytics_overview(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    campaigns = db.query(Campaign).filter(Campaign.user_id == current_user.id).all()
    logs = db.query(EmailLog).filter(EmailLog.user_id == current_user.id).all()

    total_sent = len([log for log in logs if log.status in {"sent", "delivered", "read", "clicked", "replied"}])
    total_opened = len([log for log in logs if log.status in {"read", "clicked", "replied"}])
    total_replied = len([log for log in logs if log.status == "replied"])

    daily_points = {}
    for log in logs:
        date_key = log.timestamp.date().isoformat() if log.timestamp else None
        if not date_key:
            continue
        daily_points.setdefault(date_key, {"date": date_key, "opens": 0, "replies": 0, "clicks": 0})
        if log.status in {"read", "clicked", "replied"}:
            daily_points[date_key]["opens"] += 1
        if log.status == "clicked":
            daily_points[date_key]["clicks"] += 1
        if log.status == "replied":
            daily_points[date_key]["replies"] += 1

    best_campaigns = []
    for campaign in campaigns:
        stats = db.query(
            Lead.status,
            func.count(Lead.id)
        ).filter(Lead.campaign_id == campaign.id).group_by(Lead.status).all()
        mapped = {status: count for status, count in stats}
        sent = mapped.get("sent", 0) + mapped.get("read", 0) + mapped.get("clicked", 0) + mapped.get("replied", 0)
        replies = mapped.get("replied", 0)
        best_campaigns.append({
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "sent": sent,
            "replies": replies,
            "reply_rate": round((replies / sent) * 100, 2) if sent else 0,
        })

    sequence_step_stats = []
    step_rows = db.query(
        EmailLog.sequence_step_id,
        func.count(EmailLog.id).label("sent_count"),
        func.sum(case((EmailLog.status == "replied", 1), else_=0)).label("reply_count"),
    ).filter(
        EmailLog.user_id == current_user.id,
        EmailLog.sequence_step_id.isnot(None)
    ).group_by(EmailLog.sequence_step_id).all()

    for step_id, sent_count, reply_count in step_rows:
        sequence_step_stats.append({
            "sequence_step_id": step_id,
            "sent": sent_count or 0,
            "replies": reply_count or 0,
            "reply_rate": round(((reply_count or 0) / (sent_count or 1)) * 100, 2) if sent_count else 0,
        })

    send_heatmap = []
    heatmap_rows = db.query(
        func.strftime("%H", EmailLog.timestamp).label("hour"),
        func.count(EmailLog.id)
    ).filter(
        EmailLog.user_id == current_user.id
    ).group_by("hour").all()
    for hour, count in heatmap_rows:
        send_heatmap.append({"hour": hour, "count": count})

    return {
        "summary": {
            "campaigns": len(campaigns),
            "emails_sent": total_sent,
            "open_rate": round((total_opened / total_sent) * 100, 2) if total_sent else 0,
            "reply_rate": round((total_replied / total_sent) * 100, 2) if total_sent else 0,
        },
        "open_rate_over_time": sorted(daily_points.values(), key=lambda point: point["date"]),
        "best_campaigns": sorted(best_campaigns, key=lambda campaign: campaign["reply_rate"], reverse=True)[:10],
        "reply_rate_by_sequence_step": sequence_step_stats,
        "best_time_of_day": send_heatmap,
    }


@router.get("/account-activity")
async def get_account_activity(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    today = datetime.now(pytz.UTC).date()
    activity = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        sent = db.query(func.count(EmailLog.id)).filter(
            EmailLog.user_id == current_user.id,
            func.date(EmailLog.timestamp) == day,
            EmailLog.status.in_(["sent", "delivered", "read", "clicked", "replied"]),
        ).scalar() or 0
        replies = db.query(func.count(EmailLog.id)).filter(
            EmailLog.user_id == current_user.id,
            func.date(EmailLog.timestamp) == day,
            EmailLog.status == "replied",
        ).scalar() or 0
        activity.append({
            "date": day.isoformat(),
            "sent": sent,
            "replies": replies,
        })

    return {"activity": activity}

@router.get("/dev/test-emails")
async def get_test_emails():
    """Get all test emails sent in development mode."""
    import os
    import json
    from ..config import settings
    
    if not settings.DEV_MODE:
        raise HTTPException(status_code=404, detail="Dev mode is disabled")
    
    test_inbox_path = settings.TEST_EMAIL_INBOX
    emails = []
    
    if os.path.exists(test_inbox_path):
        for filename in sorted(os.listdir(test_inbox_path), reverse=True):
            if filename.endswith('.json'):
                filepath = os.path.join(test_inbox_path, filename)
                try:
                    with open(filepath, 'r') as f:
                        email_data = json.load(f)
                        emails.append(email_data)
                except Exception as e:
                    print(f"Error reading {filename}: {str(e)}")
    
    return {
        "dev_mode": settings.DEV_MODE,
        "test_inbox": test_inbox_path,
        "total_emails": len(emails),
        "emails": emails[:50]  # Return last 50 emails
    }
