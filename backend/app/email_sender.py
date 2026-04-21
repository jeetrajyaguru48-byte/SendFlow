import random
import time
import re
import hmac
import hashlib
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Dict, Optional
import pytz

from .database import SessionLocal
from .models import (
    Campaign, Lead, EmailLog, User, Sequence, SequenceStep, 
    SequenceEnrollment, DailySendLog
)
from .gmail_service import send_message, check_for_bounces_and_replies
from .tracking import generate_tracking_id, process_message_with_tracking
from .config import settings
from .url_utils import is_public_https_url
from .time_utils import (
    is_within_daily_window,
    minutes_since_midnight,
    parse_hhmm,
    safe_localize,
    to_utc,
)


DEFAULT_CAMPAIGN_WINDOW_START = "15:00"
DEFAULT_CAMPAIGN_WINDOW_END = "21:00"


def make_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def get_current_daily_limit(user: User) -> int:
    """Get the current daily email limit for a user based on warm-up stage."""
    configured_limit = user.custom_daily_limit or user.daily_limit
    if user.warmup_stage == 0:
        return configured_limit  # Default 30
    
    # Warm-up stages: 5, 10, 15, 20, 25, 30 emails per day
    warmup_limits = [5, 10, 15, 20, 25, 30]
    if 1 <= user.warmup_stage <= len(warmup_limits):
        return warmup_limits[user.warmup_stage - 1]
    return configured_limit

def get_emails_sent_today(user_id: int, db: Session) -> int:
    """Get the number of emails sent today by a user."""
    today = datetime.now(timezone.utc).date()
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    today_end = datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc)
    
    sent_count = db.query(func.count(EmailLog.id)).filter(
        EmailLog.user_id == user_id,
        EmailLog.timestamp >= today_start,
        EmailLog.timestamp <= today_end,
        EmailLog.status != "failed"
    ).scalar()
    
    return sent_count or 0

def get_pending_emails_for_user(user_id: int, db: Session) -> List[Dict]:
    """Get all pending emails for a user across campaigns and sequences."""
    pending_emails = []
    
    # Get pending campaign leads
    campaign_leads = db.query(Lead, Campaign).join(Campaign).filter(
        Campaign.user_id == user_id,
        Lead.status == "pending",
        Lead.opted_out.is_(False),
        Campaign.status == "running"
    ).all()
    
    for lead, campaign in campaign_leads:
        pending_emails.append({
            "type": "campaign",
            "lead": lead,
            "campaign": campaign,
            "sequence_step": None,
            "priority": lead.priority,
            "scheduled_time": None
        })
    
    # Get pending sequence enrollments
    sequence_enrollments = db.query(SequenceEnrollment, Lead, Sequence).join(
        Lead, SequenceEnrollment.lead_id == Lead.id
    ).join(
        Sequence, SequenceEnrollment.sequence_id == Sequence.id
    ).filter(
        Sequence.user_id == user_id,
        SequenceEnrollment.completed_at.is_(None),
        SequenceEnrollment.paused_at.is_(None),
        Lead.opted_out.is_(False),
        Lead.status.in_(["pending", "sent"])  # Allow sequence emails even if previously contacted
    ).all()
    
    for enrollment, lead, sequence in sequence_enrollments:
        # Check if next step is due
        next_step = db.query(SequenceStep).filter(
            SequenceStep.sequence_id == sequence.id,
            SequenceStep.step_number == enrollment.current_step
        ).first()
        
        if next_step and enrollment.next_send_at:
            next_send_at = make_utc_aware(enrollment.next_send_at)
            if next_send_at <= datetime.now(timezone.utc):
                pending_emails.append({
                    "type": "sequence",
                    "lead": lead,
                    "campaign": None,
                    "sequence_step": next_step,
                    "priority": next_step.priority,
                    "scheduled_time": next_send_at
                })
    
    # Sort by priority (high > normal > low) then by scheduled time
    priority_order = {"high": 0, "normal": 1, "low": 2}
    pending_emails.sort(key=lambda x: (
        priority_order.get(x["priority"], 1),
        x["scheduled_time"] or datetime.max.replace(tzinfo=timezone.utc)
    ))
    
    return pending_emails

def get_campaign_timezone(user: User, campaign: Optional[Campaign]) -> pytz.BaseTzInfo:
    timezone_name = (campaign.timezone if campaign and campaign.timezone else user.timezone) or "UTC"
    try:
        return pytz.timezone(timezone_name)
    except Exception:
        return pytz.UTC


def get_campaign_window(campaign: Optional[Campaign]) -> tuple[int, int, bool]:
    start_value = campaign.send_window_start if campaign and campaign.send_window_start else DEFAULT_CAMPAIGN_WINDOW_START
    end_value = campaign.send_window_end if campaign and campaign.send_window_end else DEFAULT_CAMPAIGN_WINDOW_END
    start_hour, start_minute = parse_hhmm(start_value, default=DEFAULT_CAMPAIGN_WINDOW_START)
    end_hour, end_minute = parse_hhmm(end_value, default=DEFAULT_CAMPAIGN_WINDOW_END)
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    weekdays_only = bool(campaign.send_window_weekdays_only) if campaign else False
    return start_minutes, end_minutes, weekdays_only


def is_optimal_send_time(user: User, lead: Lead, sequence_step: Optional[SequenceStep] = None, campaign: Optional[Campaign] = None) -> bool:
    """Check if current time is optimal for sending to this lead."""
    now = datetime.now(timezone.utc)

    start_minutes = 9 * 60
    end_minutes = 17 * 60
    weekdays_only = True
    local_now = now.astimezone(pytz.timezone(lead.timezone or user.timezone or "UTC"))

    if sequence_step:
        if sequence_step.send_window_start:
            h, m = parse_hhmm(sequence_step.send_window_start, default="09:00")
            start_minutes = h * 60 + m
        if sequence_step.send_window_end:
            h, m = parse_hhmm(sequence_step.send_window_end, default="17:00")
            end_minutes = h * 60 + m
        weekdays_only = sequence_step.weekdays_only
    elif campaign:
        start_minutes, end_minutes, weekdays_only = get_campaign_window(campaign)
        local_now = now.astimezone(get_campaign_timezone(user, campaign))

    if weekdays_only and local_now.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    
    return is_within_daily_window(minutes_since_midnight(local_now), start_minutes, end_minutes)

def parse_spintax(text: str) -> str:
    """Expand simple spintax syntax in a template string."""
    if not text:
        return text

    pattern = re.compile(r"\{([^{}]+)\}")

    def replace(match):
        options = match.group(1).split("|")
        return random.choice(options).strip()

    while True:
        new_text = pattern.sub(replace, text)
        if new_text == text:
            break
        text = new_text

    return text


def generate_unsubscribe_token(lead_id: int) -> str:
    secret = settings.SECRET_KEY.encode("utf-8")
    payload = str(lead_id).encode("utf-8")
    digest = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{lead_id}:{digest}"


def verify_unsubscribe_token(token: str) -> Optional[int]:
    try:
        lead_id_text, signature = token.split(":", 1)
        expected = hmac.new(settings.SECRET_KEY.encode("utf-8"), lead_id_text.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature):
            return int(lead_id_text)
    except Exception:
        return None
    return None


def get_unsubscribe_url(lead: Lead) -> str:
    if not is_public_https_url(settings.BASE_URL):
        return ""
    token = generate_unsubscribe_token(lead.id)
    return f"{settings.BASE_URL}/unsubscribe/{token}"


def get_delay_seconds(campaign: Optional[Campaign] = None) -> int:
    min_delay = settings.MIN_DELAY_MINUTES
    max_delay = settings.MAX_DELAY_MINUTES
    if campaign:
        if campaign.min_delay_minutes is not None:
            min_delay = campaign.min_delay_minutes
        if campaign.max_delay_minutes is not None:
            max_delay = campaign.max_delay_minutes
    min_delay = max(0, min_delay)
    max_delay = max(min_delay, max_delay)
    return random.randint(min_delay, max_delay) * 60


def get_hourly_spacing_seconds(campaign: Optional[Campaign] = None) -> int:
    hourly_rate = 5
    if campaign and campaign.hourly_send_rate:
        hourly_rate = max(1, campaign.hourly_send_rate)
    return max(60, int(3600 / hourly_rate))


def get_even_campaign_spacing_seconds(user: User, campaign: Campaign) -> int:
    start_minutes, end_minutes, _ = get_campaign_window(campaign)
    window_minutes = (end_minutes - start_minutes) % (24 * 60)
    if window_minutes == 0:
        window_minutes = 24 * 60
    window_seconds = max(3600, window_minutes * 60)
    daily_limit = max(1, get_current_daily_limit(user))
    return max(60, int(window_seconds / daily_limit))


def get_next_campaign_send_time(user: User, campaign: Campaign, now: Optional[datetime] = None) -> datetime:
    reference_time = make_utc_aware(now) or datetime.now(timezone.utc)
    spacing_seconds = get_even_campaign_spacing_seconds(user, campaign)
    return reference_time + timedelta(seconds=spacing_seconds)


def get_campaign_sent_last_hour(campaign_id: int, db: Session) -> int:
    """Return how many emails this campaign sent in the last rolling hour."""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    sent_count = db.query(func.count(EmailLog.id)).filter(
        EmailLog.campaign_id == campaign_id,
        EmailLog.timestamp >= one_hour_ago,
        EmailLog.status.in_(["sent", "delivered"]),
    ).scalar()
    return sent_count or 0


def get_display_name_parts(lead: Lead) -> tuple[str, str]:
    raw_name = (lead.name or "").strip()
    custom_first_name = ""
    if lead.custom_fields:
        custom_first_name = str(lead.custom_fields.get("first_name") or "").strip()

    candidate = raw_name or custom_first_name or lead.email.split("@")[0]
    if "@" in candidate:
        candidate = candidate.split("@")[0]

    candidate = re.sub(r"[._\-+]+", " ", candidate)
    candidate = re.sub(r"\d+", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ._-")

    words = [word.capitalize() for word in candidate.split() if word]
    if not words:
        fallback = lead.email.split("@")[0].strip(" ._-").capitalize() or "There"
        return fallback, fallback

    full_name = " ".join(words)
    first_name = (custom_first_name.split()[0].capitalize() if custom_first_name else words[0])
    return first_name, full_name

def personalize_content(content: str, lead: Lead) -> str:
    """Replace merge tags with lead data."""
    first_name, display_name = get_display_name_parts(lead)
    name_parts = display_name.split()
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    replacements = {
        "{{first_name}}": first_name,
        "{{last_name}}": last_name,
        "{{name}}": display_name,
        "{{email}}": lead.email,
        "{first_name}": first_name,
        "{last_name}": last_name,
        "{name}": display_name,
        "{email}": lead.email,
    }
    
    # Add custom fields
    if lead.custom_fields:
        for key, value in lead.custom_fields.items():
            replacements[f"{{{{custom_{key}}}}}"] = str(value)
            replacements[f"{{custom_{key}}}"] = str(value)
    
    for tag, value in replacements.items():
        content = content.replace(tag, value)
    
    return content

def send_single_email(lead: Lead, campaign: Optional[Campaign], sequence_step: Optional[SequenceStep], 
                     user: User, db: Session, variant: Optional[str] = None) -> bool:
    """Send a single email with all personalization and tracking."""
    subject = None
    body = None
    try:
        tracking_id = generate_tracking_id()
        
        # Determine content source
        if sequence_step:
            subject = sequence_step.subject
            body = sequence_step.body
            sender_name = sequence_step.sender_name
        else:
            fallback_first_name, _ = get_display_name_parts(lead)
            subject = campaign.subject_template if campaign and campaign.subject_template else f"Hello {fallback_first_name}"
            body = campaign.message_template if campaign else ""
            sender_name = None

        # Apply variation and personalization
        subject = parse_spintax(subject)
        body = parse_spintax(body)
        subject = personalize_content(subject, lead)
        body = personalize_content(body, lead)

        # Add A/B testing variant to subject if applicable
        if variant:
            subject = f"[{variant}] {subject}"

        base_url_is_safe = is_public_https_url(settings.BASE_URL)

        # Append unsubscribe instructions (avoid localhost/non-https links in real email).
        unsubscribe_url = get_unsubscribe_url(lead) if base_url_is_safe else ""
        if unsubscribe_url:
            body = f"{body}\n\nIf you no longer wish to receive these messages, unsubscribe here: {unsubscribe_url}"
        else:
            body = f"{body}\n\nIf you no longer wish to receive these messages, reply with “unsubscribe”."

        # Process tracking only when we have a public https base URL configured.
        if settings.EMAIL_TRACKING_ENABLED and base_url_is_safe:
            tracked_body = process_message_with_tracking(body, tracking_id, settings.BASE_URL)
        else:
            tracked_body = body
        
        # Send email
        sent_message = send_message(
            user=user,
            to=lead.email,
            subject=subject,
            body=tracked_body,
            sender_name=sender_name,
            unsubscribe_link=unsubscribe_url or None,
            unsubscribe_mailto=user.email,
        )
        
        # Log the email
        email_log = EmailLog(
            user_id=user.id,
            campaign_id=campaign.id if campaign else None,
            lead_id=lead.id,
            tracking_id=tracking_id,
            message_id=sent_message.get("id"),
            thread_id=sent_message.get("threadId"),
            subject=subject,
            body=tracked_body,
            status="sent",
            variant=variant,
            sequence_step_id=sequence_step.id if sequence_step else None
        )
        db.add(email_log)
        
        # Update lead status
        lead.status = "sent"
        lead.sent_at = datetime.now(timezone.utc)
        lead.last_contacted_at = datetime.now(timezone.utc)
        lead.lifecycle_stage = "contacted"
        
        # Update sequence enrollment if applicable
        if sequence_step:
            enrollment = db.query(SequenceEnrollment).filter(
                SequenceEnrollment.lead_id == lead.id,
                SequenceEnrollment.sequence_id == sequence_step.sequence_id
            ).first()
            if enrollment:
                enrollment.current_step += 1
                # Schedule next step if exists
                next_step = db.query(SequenceStep).filter(
                    SequenceStep.sequence_id == sequence_step.sequence_id,
                    SequenceStep.step_number == enrollment.current_step
                ).first()
                if next_step:
                    enrollment.next_send_at = datetime.now(timezone.utc) + timedelta(hours=next_step.delay_hours)
                else:
                    enrollment.completed_at = datetime.now(timezone.utc)
        
        db.commit()
        return True
        
    except Exception as e:
        # Log failed email
        error_msg = str(e)
        print(f"❌ Failed to send email to {lead.email}: {error_msg}")
        
        email_log = EmailLog(
            user_id=user.id,
            campaign_id=campaign.id if campaign else None,
            lead_id=lead.id,
            tracking_id=generate_tracking_id(),
            subject=subject if subject else "Failed email",
            body=body if body else "",
            status="failed",
            error_message=error_msg,
            variant=variant,
            sequence_step_id=sequence_step.id if sequence_step else None
        )
        db.add(email_log)
        db.commit()
        return False

def seconds_until_next_send_window(user: User, lead: Lead, campaign: Optional[Campaign] = None, sequence_step: Optional[SequenceStep] = None) -> int:
    """Return seconds until the next allowable send window for the lead."""
    now = datetime.now(timezone.utc)
    recipient_tz = pytz.timezone(lead.timezone or user.timezone or "UTC")
    local_now = now.astimezone(recipient_tz)

    start_minutes = 9 * 60
    end_minutes = 17 * 60
    weekdays_only = True

    if sequence_step:
        if sequence_step.send_window_start:
            h, m = parse_hhmm(sequence_step.send_window_start, default="09:00")
            start_minutes = h * 60 + m
        if sequence_step.send_window_end:
            h, m = parse_hhmm(sequence_step.send_window_end, default="17:00")
            end_minutes = h * 60 + m
        weekdays_only = sequence_step.weekdays_only
    elif campaign:
        recipient_tz = get_campaign_timezone(user, campaign)
        local_now = now.astimezone(recipient_tz)
        start_minutes, end_minutes, weekdays_only = get_campaign_window(campaign)

    if weekdays_only and local_now.weekday() >= 5:
        # Next weekday at window start.
        target_date = (local_now + timedelta(days=1)).date()
    else:
        current_minutes = minutes_since_midnight(local_now)
        if is_within_daily_window(current_minutes, start_minutes, end_minutes) and (not weekdays_only or local_now.weekday() < 5):
            return 60
        if current_minutes < start_minutes:
            target_date = local_now.date()
        else:
            target_date = (local_now + timedelta(days=1)).date()

    while weekdays_only and datetime(target_date.year, target_date.month, target_date.day).weekday() >= 5:
        target_date = (datetime(target_date.year, target_date.month, target_date.day) + timedelta(days=1)).date()

    start_hour = start_minutes // 60
    start_minute = start_minutes % 60
    target_naive = datetime(target_date.year, target_date.month, target_date.day, start_hour, start_minute, 0, 0)
    target_local = safe_localize(recipient_tz, target_naive)
    target_utc = target_local.astimezone(timezone.utc)
    wait_seconds = (target_utc - now).total_seconds()
    return int(max(60, wait_seconds))


def send_campaign_emails(campaign_id: int, user_id: int, force_send: bool = False):
    """Process a single due batch for a campaign without long-lived worker sleeps."""
    db: Session = SessionLocal()
    campaign = None
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        user = db.query(User).filter(User.id == user_id).first()

        if not campaign or not user:
            print(f"❌ Campaign {campaign_id} or User {user_id} not found")
            return
        if campaign.status == "paused" and not force_send:
            return {
                "campaign_id": campaign_id,
                "status": "paused",
                "sent": 0,
                "failed": 0,
                "remaining": db.query(func.count(Lead.id)).filter(
                    Lead.campaign_id == campaign_id,
                    Lead.status == "pending",
                    Lead.opted_out.is_(False),
                ).scalar() or 0,
                "reason": "campaign_paused",
                "next_send_at": None,
            }

        now = datetime.now(timezone.utc)

        # Respect future campaign start times unless explicitly forced.
        campaign_start = to_utc(campaign.send_start_time, campaign.timezone or user.timezone)
        if campaign_start and not force_send and now < campaign_start:
            campaign.status = "scheduled"
            db.commit()
            return {
                "campaign_id": campaign_id,
                "status": "scheduled",
                "sent": 0,
                "failed": 0,
                "remaining": db.query(func.count(Lead.id)).filter(
                    Lead.campaign_id == campaign_id,
                    Lead.status == "pending",
                    Lead.opted_out.is_(False),
                ).scalar() or 0,
                "reason": "campaign_not_started",
                "next_send_at": campaign_start.isoformat(),
            }

        scheduled_next_send = to_utc(campaign.next_send_at, "UTC")
        if scheduled_next_send and not force_send and scheduled_next_send > now:
            campaign.status = "scheduled"
            db.commit()
            return {
                "campaign_id": campaign_id,
                "status": "scheduled",
                "sent": 0,
                "failed": 0,
                "remaining": db.query(func.count(Lead.id)).filter(
                    Lead.campaign_id == campaign_id,
                    Lead.status == "pending",
                    Lead.opted_out.is_(False),
                ).scalar() or 0,
                "reason": "waiting_for_next_send_slot",
                "next_send_at": scheduled_next_send.isoformat(),
            }

        campaign.status = "running"
        db.commit()
        
        # Get daily limits and respect warm-up stages
        daily_limit = get_current_daily_limit(user)
        emails_sent_today = get_emails_sent_today(user_id, db)
        
        if emails_sent_today >= daily_limit:
            # Daily limit reached
            print(f"Daily limit reached for campaign {campaign_id}")
            campaign.status = "paused"
            db.commit()
            return {
                "campaign_id": campaign_id,
                "status": "paused",
                "sent": 0,
                "failed": 0,
                "remaining": db.query(func.count(Lead.id)).filter(
                    Lead.campaign_id == campaign_id,
                    Lead.status == "pending",
                    Lead.opted_out.is_(False),
                ).scalar() or 0,
                "reason": "daily_limit_reached",
                "next_send_at": None,
            }

        # Get pending emails for this campaign and exclude unsubscribed recipients
        pending_leads = db.query(Lead).filter(
            Lead.campaign_id == campaign_id,
            Lead.status == "pending",
            Lead.opted_out.is_(False)
        ).all()
        
        if not pending_leads:
            print(f"✅ No pending leads for campaign {campaign_id}")
            campaign.status = "completed"
            db.commit()
            return {
                "campaign_id": campaign_id,
                "status": "completed",
                "sent": 0,
                "failed": 0,
                "remaining": 0,
                "reason": "no_pending_leads",
            }

        sent_last_hour = 0 if force_send else get_campaign_sent_last_hour(campaign_id, db)
        hourly_limit = max(1, campaign.hourly_send_rate or 5)
        if not force_send and sent_last_hour >= hourly_limit:
            campaign.next_send_at = now + timedelta(seconds=get_even_campaign_spacing_seconds(user, campaign))
            campaign.status = "scheduled"
            db.commit()
            return {
                "campaign_id": campaign_id,
                "status": "scheduled",
                "sent": 0,
                "failed": 0,
                "remaining": len(pending_leads),
                "reason": "hourly_limit_reached",
                "next_send_at": campaign.next_send_at.isoformat() if campaign.next_send_at else None,
            }
        
        emails_sent_this_batch = 0
        emails_failed_this_batch = 0

        next_window_wait_seconds = None
        for lead in pending_leads:
            # Skip until the next cron tick if the lead is outside the allowed send window.
            if not force_send and not is_optimal_send_time(user, lead, None, campaign):
                wait_seconds = seconds_until_next_send_window(user, lead, campaign=campaign)
                next_window_wait_seconds = wait_seconds if next_window_wait_seconds is None else min(next_window_wait_seconds, wait_seconds)
                continue

            # Handle A/B testing
            variant = None
            if campaign.ab_test_config and campaign.ab_test_config.get("enabled"):
                variants = campaign.ab_test_config.get("variants", [])
                if variants:
                    variant = random.choice(variants)["name"]
            
            # Send the email
            success = send_single_email(lead, campaign, None, user, db, variant)
            
            if success:
                emails_sent_this_batch += 1
                
                # Update daily log
                today = datetime.now(timezone.utc).date()
                daily_log = db.query(DailySendLog).filter(
                    DailySendLog.user_id == user_id,
                    func.date(DailySendLog.date) == today
                ).first()
                
                if not daily_log:
                    daily_log = DailySendLog(
                        user_id=user_id,
                        date=datetime.now(timezone.utc),
                        emails_sent=0,
                        emails_queued=0
                    )
                    db.add(daily_log)
                
                daily_log.emails_sent += 1
                db.commit()
            else:
                emails_failed_this_batch += 1

            break

        if emails_sent_this_batch == 0 and emails_failed_this_batch == 0:
            if next_window_wait_seconds is not None:
                campaign.next_send_at = now + timedelta(seconds=next_window_wait_seconds)
            else:
                campaign.next_send_at = now + timedelta(seconds=get_even_campaign_spacing_seconds(user, campaign))
            campaign.status = "scheduled"
            db.commit()
            return {
                "campaign_id": campaign_id,
                "status": "scheduled",
                "sent": 0,
                "failed": 0,
                "remaining": len(pending_leads),
                "reason": "outside_send_window",
                "next_send_at": campaign.next_send_at.isoformat() if campaign.next_send_at else None,
            }
        
        # Update batch counter
        campaign.emails_sent_in_batch += emails_sent_this_batch
        
        # Check if campaign is complete
        remaining_pending = db.query(Lead).filter(
            Lead.campaign_id == campaign_id,
            Lead.status == "pending"
        ).count()
        
        if remaining_pending == 0:
            campaign.status = "completed"
            campaign.next_send_at = None
            print(f"✅ Campaign {campaign_id} completed! Sent {campaign.emails_sent_in_batch} emails total.")
        elif emails_sent_today + emails_sent_this_batch >= daily_limit:
            campaign.status = "paused"
            campaign.next_send_at = None
            print(f"⏸️ Campaign {campaign_id} paused after hitting daily limit. Sent {emails_sent_this_batch}, Failed {emails_failed_this_batch}. Remaining: {remaining_pending}")
        else:
            campaign.status = "scheduled"
            campaign.next_send_at = None if force_send else get_next_campaign_send_time(user, campaign, now=datetime.now(timezone.utc))
            print(f"📋 Campaign {campaign_id} scheduled for the next scheduler run. Sent {emails_sent_this_batch}, Failed {emails_failed_this_batch}. Remaining: {remaining_pending}")
        
        db.commit()
        return {
            "campaign_id": campaign_id,
            "status": campaign.status,
            "sent": emails_sent_this_batch,
            "failed": emails_failed_this_batch,
            "remaining": remaining_pending,
            "next_send_at": campaign.next_send_at.isoformat() if campaign.next_send_at else None,
        }

    except Exception as e:
        print(f"❌ Error in send_campaign_emails: {str(e)}")
        if campaign:
            campaign.status = "failed"
            db.commit()
        raise
    finally:
        db.close()


def process_due_campaigns() -> Dict[str, object]:
    """Run one scheduler tick across all campaigns that should send now."""
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        campaigns = db.query(Campaign).filter(
            Campaign.status.in_(["scheduled", "queued", "running"])
        ).all()

        results = []
        for campaign in campaigns:
            pending_count = db.query(func.count(Lead.id)).filter(
                Lead.campaign_id == campaign.id,
                Lead.status == "pending",
                Lead.opted_out.is_(False),
            ).scalar() or 0
            if pending_count == 0:
                if campaign.status != "completed":
                    campaign.status = "completed"
                continue

            campaign_start = to_utc(campaign.send_start_time, campaign.timezone)
            if campaign_start and campaign_start > now:
                campaign.status = "scheduled"
                continue

            results.append(send_campaign_emails(campaign.id, campaign.user_id, force_send=False))

        db.commit()
        return {
            "processed_campaigns": len(results),
            "results": results,
            "ran_at": now.isoformat(),
        }
    finally:
        db.close()


def sync_bounces_and_replies_once(max_logs: int = 25) -> Dict[str, int]:
    """One-pass inbox sync for scheduler usage."""
    db: Session = SessionLocal()
    checked = 0
    updated = 0
    try:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        sent_logs = db.query(EmailLog).filter(
            EmailLog.status == "sent",
            EmailLog.timestamp >= seven_days_ago
        ).order_by(EmailLog.timestamp.desc()).limit(max_logs).all()

        for log in sent_logs:
            try:
                user = db.query(User).filter(User.id == log.user_id).first()
                if not user or not log.message_id:
                    continue

                checked += 1
                result = check_for_bounces_and_replies(user, log.message_id)
                lead = db.query(Lead).filter(Lead.id == log.lead_id).first()
                if not lead:
                    continue

                before_status = log.status
                if result['has_bounce']:
                    log.status = "bounced"
                    lead.status = "bounced"
                    lead.bounced_at = datetime.utcnow()
                    lead.lifecycle_stage = "unsubscribed"
                elif result['has_reply']:
                    log.status = "replied"
                    lead.status = "replied"
                    lead.replied_at = datetime.utcnow()
                    lead.reply_category = result.get('reply_category')
                    lead.lifecycle_stage = "replied"
                    lead.lead_score = (lead.lead_score or 0) + 15
                    if result.get('reply_category') in {"interested", "referral"}:
                        lead.needs_follow_up = True
                    reply_content = (result.get("reply_content") or "").lower()
                    if "unsubscribe" in reply_content or "remove me" in reply_content:
                        lead.opted_out = True
                        lead.opted_out_at = datetime.utcnow()
                        lead.lifecycle_stage = "unsubscribed"

                if log.status != before_status:
                    updated += 1
                db.commit()
            except Exception as e:
                print(f"Error checking bounce/reply for log {log.id}: {str(e)}")
                continue

        return {"checked": checked, "updated": updated, "scanned": len(sent_logs)}
    finally:
        db.close()

async def run_bounce_and_reply_loop():
    """Background task to check for bounces and replies."""
    while True:
        try:
            sync_bounces_and_replies_once()
        except Exception as e:
            print(f"Error in check_bounces_and_replies: {str(e)}")

        # Check every hour
        await asyncio.sleep(3600)
