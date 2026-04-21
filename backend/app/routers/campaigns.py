from datetime import datetime
import io
import re
from typing import Dict, List, Optional

import pandas as pd
import pytz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..email_sender import send_campaign_emails
from ..models import Campaign, EmailLog, Lead
from ..config import settings
from ..time_utils import to_utc
from ..schemas import Campaign as CampaignSchema
from ..schemas import (
    CampaignCreate,
    LeadBulkAssignRequest,
    LeadBulkDeleteRequest,
    LeadImportConfirmRequest,
    LeadManualCreateRequest,
    LeadStageUpdateRequest,
)

router = APIRouter()


LEAD_COLUMN_ALIASES: Dict[str, List[str]] = {
    "email": ["email", "personal_email", "primary_email", "contact_email", "work_email"],
    "name": ["name", "full_name", "contact_name"],
    "first_name": ["first_name", "firstname"],
    "last_name": ["last_name", "lastname"],
    "company": ["company", "organization", "account"],
    "title": ["title", "job_title", "role", "designation"],
    "phone": ["phone", "phone_number", "mobile"],
    "website": ["website", "domain", "company_website"],
    "linkedin_url": ["linkedin", "linkedin_url", "linkedin_profile"],
    "location": ["location", "city", "region", "country"],
    "source": ["source", "lead_source", "channel"],
    "notes": ["notes", "note", "comment", "comments"],
    "timezone": ["timezone", "time_zone", "tz"],
    "priority": ["priority", "lead_priority"],
}


def _get_owned_campaign(campaign_id: int, user_id: int, db: Session) -> Campaign:
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.user_id == user_id,
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _build_campaign_status(campaign: Campaign, force_send: bool = False) -> str:
    if force_send:
        return "running"
    return "scheduled"


def _activate_campaign(campaign: Campaign, db: Session, force_send: bool = False):
    pending_leads_count = db.query(Lead).filter(
        Lead.campaign_id == campaign.id,
        Lead.status == "pending",
        Lead.opted_out.is_(False),
    ).count()
    if pending_leads_count == 0:
        raise HTTPException(status_code=400, detail="Campaign has no pending leads to send")

    if campaign.status == "running":
        raise HTTPException(status_code=400, detail="Campaign is already running")

    campaign.status = _build_campaign_status(campaign, force_send=force_send)
    campaign.next_send_at = datetime.now(pytz.UTC) if force_send else None
    db.commit()


def _campaign_next_run_hint(campaign: Campaign):
    return campaign.next_send_at or campaign.send_start_time


def _find_column(headers: List[str], lower_headers: List[str], candidates: List[str]) -> str:
    for candidate in candidates:
        if candidate in lower_headers:
            return headers[lower_headers.index(candidate)]
    return ""


def _clean_value(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _normalize_lead_name(name_value: Optional[str], email_value: str) -> str:
    candidate = (name_value or "").strip()
    if not candidate:
        candidate = email_value.split("@")[0]
    if "@" in candidate:
        candidate = candidate.split("@")[0]
    candidate = re.sub(r"[._\-+]+", " ", candidate)
    candidate = re.sub(r"\d+", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ._-")
    if not candidate:
        candidate = email_value.split("@")[0]
    words = [word for word in candidate.split(" ") if word]
    if not words:
        return email_value.split("@")[0].capitalize()
    return " ".join(word.capitalize() for word in words)


def _build_lead_from_mapping(campaign_id: int, row: dict, mapping: dict) -> Lead:
    email_header = mapping.get("email")
    if not email_header:
        raise HTTPException(status_code=400, detail="Lead mapping must include an email column")

    email_value = _clean_value(row.get(email_header))
    if not email_value:
        raise HTTPException(status_code=400, detail="A mapped lead row is missing an email value")

    name_value = _clean_value(row.get(mapping.get("name", ""))) if mapping.get("name") else None
    if not name_value:
        first_name = _clean_value(row.get(mapping.get("first_name", ""))) if mapping.get("first_name") else ""
        last_name = _clean_value(row.get(mapping.get("last_name", ""))) if mapping.get("last_name") else ""
        name_value = f"{first_name or ''} {last_name or ''}".strip() or email_value.split("@")[0]
    name_value = _normalize_lead_name(name_value, email_value)

    mapped_headers = {header for header in mapping.values() if header}
    custom_fields = {}
    for key, value in row.items():
        if key in mapped_headers:
            continue
        cleaned = _clean_value(value)
        if cleaned is not None:
            custom_fields[key] = cleaned

    return Lead(
        campaign_id=campaign_id,
        email=email_value,
        name=name_value,
        company=_clean_value(row.get(mapping.get("company", ""))) if mapping.get("company") else None,
        title=_clean_value(row.get(mapping.get("title", ""))) if mapping.get("title") else None,
        phone=_clean_value(row.get(mapping.get("phone", ""))) if mapping.get("phone") else None,
        website=_clean_value(row.get(mapping.get("website", ""))) if mapping.get("website") else None,
        linkedin_url=_clean_value(row.get(mapping.get("linkedin_url", ""))) if mapping.get("linkedin_url") else None,
        location=_clean_value(row.get(mapping.get("location", ""))) if mapping.get("location") else None,
        source=_clean_value(row.get(mapping.get("source", ""))) if mapping.get("source") else None,
        notes=_clean_value(row.get(mapping.get("notes", ""))) if mapping.get("notes") else None,
        timezone=_clean_value(row.get(mapping.get("timezone", ""))) if mapping.get("timezone") else None,
        priority=_clean_value(row.get(mapping.get("priority", ""))) if mapping.get("priority") else "normal",
        custom_fields=custom_fields or None,
    )


@router.post("/", response_model=CampaignSchema)
async def create_campaign(
    campaign: CampaignCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a new campaign."""
    timezone_name = (campaign.timezone or current_user.timezone or settings.DEFAULT_TIMEZONE).strip() or settings.DEFAULT_TIMEZONE
    normalized_start = to_utc(campaign.send_start_time, timezone_name)
    db_campaign = Campaign(
        name=campaign.name,
        description=campaign.description,
        subject_template=campaign.subject_template,
        message_template=campaign.message_template,
        send_schedule=[entry.dict() for entry in campaign.send_schedule] if campaign.send_schedule else None,
        send_start_time=normalized_start,
        timezone=timezone_name,
        hourly_send_rate=campaign.hourly_send_rate,
        min_delay_minutes=campaign.min_delay_minutes,
        max_delay_minutes=campaign.max_delay_minutes,
        send_window_start=campaign.send_window_start or "15:00",
        send_window_end=campaign.send_window_end or "21:00",
        send_window_weekdays_only=campaign.send_window_weekdays_only,
        is_sequence=campaign.is_sequence,
        sequence_id=campaign.sequence_id,
        ab_test_config=campaign.ab_test_config,
        user_id=current_user.id,
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign


@router.get("/", response_model=List[CampaignSchema])
async def get_campaigns(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all campaigns for current user."""
    return db.query(Campaign).filter(Campaign.user_id == current_user.id).order_by(Campaign.created_at.desc()).all()


@router.get("/overview")
async def get_campaign_overview(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return campaign summaries for the workspace UI."""
    campaigns = db.query(Campaign).filter(Campaign.user_id == current_user.id).order_by(Campaign.created_at.desc()).all()
    overview = []
    for campaign in campaigns:
        leads = db.query(Lead).filter(Lead.campaign_id == campaign.id).all()
        logs = db.query(EmailLog).filter(EmailLog.campaign_id == campaign.id).order_by(EmailLog.timestamp.desc()).limit(5).all()
        total_leads = len(leads)
        sent = len([lead for lead in leads if lead.status in {"sent", "read", "clicked", "replied", "bounced"}])
        replied = len([lead for lead in leads if lead.status == "replied"])
        overview.append(
            {
                "id": campaign.id,
                "name": campaign.name,
                "description": campaign.description,
                "subject_template": campaign.subject_template,
                "status": campaign.status,
                "send_start_time": campaign.send_start_time,
                "created_at": campaign.created_at,
                "sender_email": current_user.email,
                "stats": {
                    "total_leads": total_leads,
                    "sent": sent,
                    "pending": len([lead for lead in leads if lead.status == "pending"]),
                    "replied": replied,
                    "opened": len([lead for lead in leads if lead.status == "read"]),
                    "clicked": len([lead for lead in leads if lead.status == "clicked"]),
                },
                "recent_activity": [
                    {
                        "lead_email": log.lead.email if log.lead else None,
                        "status": log.status,
                        "timestamp": log.timestamp,
                        "subject": log.subject,
                    }
                    for log in logs
                ],
            }
        )
    return {"campaigns": overview, "account_email": current_user.email}


@router.get("/{campaign_id}", response_model=CampaignSchema)
async def get_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return _get_owned_campaign(campaign_id, current_user.id, db)


@router.post("/{campaign_id}/upload-leads")
async def upload_leads(
    campaign_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload leads from CSV file and preserve extra lead context."""
    _get_owned_campaign(campaign_id, current_user.id, db)

    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        headers = [str(col).strip() for col in df.columns]
        lower_headers = [col.lower() for col in headers]

        email_col = _find_column(headers, lower_headers, LEAD_COLUMN_ALIASES["email"])
        name_col = _find_column(headers, lower_headers, LEAD_COLUMN_ALIASES["name"])
        first_name_col = _find_column(headers, lower_headers, LEAD_COLUMN_ALIASES["first_name"])
        last_name_col = _find_column(headers, lower_headers, LEAD_COLUMN_ALIASES["last_name"])

        if not email_col:
            raise HTTPException(
                status_code=400,
                detail=f"CSV must contain an email column. Found columns: {', '.join(headers)}",
            )

        mapped_columns = {
            field_name: _find_column(headers, lower_headers, aliases)
            for field_name, aliases in LEAD_COLUMN_ALIASES.items()
            if field_name not in {"email", "name", "first_name", "last_name"}
        }

        existing_emails = {
            email.lower()
            for (email,) in db.query(Lead.email).filter(Lead.campaign_id == campaign_id).all()
            if email
        }
        leads_created = 0
        skipped = 0
        duplicates = 0
        for _, row in df.iterrows():
            email_value = _clean_value(row[email_col])
            if not email_value:
                skipped += 1
                continue
            if email_value.lower() in existing_emails:
                duplicates += 1
                continue

            name_value = _clean_value(row[name_col]) if name_col else None
            if not name_value and first_name_col:
                first_name = _clean_value(row[first_name_col]) or ""
                last_name = _clean_value(row[last_name_col]) if last_name_col else ""
                last_name = last_name or ""
                name_value = f"{first_name} {last_name}".strip()
            if not name_value:
                name_value = email_value.split("@")[0]
            name_value = _normalize_lead_name(name_value, email_value)

            custom_fields = {}
            for header in headers:
                if header in {
                    email_col,
                    name_col,
                    first_name_col,
                    last_name_col,
                    *[value for value in mapped_columns.values() if value],
                }:
                    continue
                extra_value = _clean_value(row[header])
                if extra_value is not None:
                    custom_fields[header] = extra_value

            lead = Lead(
                campaign_id=campaign_id,
                email=email_value,
                name=name_value,
                company=_clean_value(row[mapped_columns["company"]]) if mapped_columns.get("company") else None,
                title=_clean_value(row[mapped_columns["title"]]) if mapped_columns.get("title") else None,
                phone=_clean_value(row[mapped_columns["phone"]]) if mapped_columns.get("phone") else None,
                website=_clean_value(row[mapped_columns["website"]]) if mapped_columns.get("website") else None,
                linkedin_url=_clean_value(row[mapped_columns["linkedin_url"]]) if mapped_columns.get("linkedin_url") else None,
                location=_clean_value(row[mapped_columns["location"]]) if mapped_columns.get("location") else None,
                source=_clean_value(row[mapped_columns["source"]]) if mapped_columns.get("source") else None,
                notes=_clean_value(row[mapped_columns["notes"]]) if mapped_columns.get("notes") else None,
                timezone=_clean_value(row[mapped_columns["timezone"]]) if mapped_columns.get("timezone") else None,
                priority=_clean_value(row[mapped_columns["priority"]]) if mapped_columns.get("priority") else "normal",
                custom_fields=custom_fields or None,
            )
            db.add(lead)
            leads_created += 1
            existing_emails.add(email_value.lower())

        db.commit()
        return {
            "message": f"Successfully uploaded {leads_created} leads",
            "leads_count": leads_created,
            "skipped_rows": skipped,
            "duplicates_skipped": duplicates,
            "mapped_fields": {k: v for k, v in mapped_columns.items() if v},
        }
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {exc}")


@router.post("/{campaign_id}/import-preview")
async def get_import_preview(
    campaign_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Preview CSV headers and suggested mapping before import."""
    _get_owned_campaign(campaign_id, current_user.id, db)

    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        headers = [str(col).strip() for col in df.columns]
        lower_headers = [col.lower() for col in headers]
        suggested_mapping = {
            field_name: _find_column(headers, lower_headers, aliases) or None
            for field_name, aliases in LEAD_COLUMN_ALIASES.items()
        }
        return {
            "headers": headers,
            "sample_rows": df.head(5).fillna("").to_dict(orient="records"),
            "rows": df.fillna("").to_dict(orient="records"),
            "suggested_mapping": suggested_mapping,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to preview import: {exc}")


@router.post("/{campaign_id}/import-with-mapping")
async def import_with_mapping(
    campaign_id: int,
    payload: LeadImportConfirmRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Import leads from client-provided rows using explicit field mapping."""
    _get_owned_campaign(campaign_id, current_user.id, db)

    existing_emails = {
        email.lower()
        for (email,) in db.query(Lead.email).filter(Lead.campaign_id == campaign_id).all()
        if email
    }

    created = 0
    duplicates = 0
    for row in payload.rows:
        try:
            lead = _build_lead_from_mapping(campaign_id, row, payload.mapping)
        except HTTPException:
            continue
        if lead.email.lower() in existing_emails:
            duplicates += 1
            continue
        db.add(lead)
        existing_emails.add(lead.email.lower())
        created += 1

    db.commit()
    return {
        "message": f"Imported {created} leads",
        "leads_count": created,
        "duplicates_skipped": duplicates,
    }


@router.post("/{campaign_id}/send")
async def send_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Start a campaign. If it has a future start time it stays scheduled until then."""
    campaign = _get_owned_campaign(campaign_id, current_user.id, db)
    _activate_campaign(campaign, db)
    return {
        "message": "Campaign scheduled for external scheduler processing" if campaign.status == "scheduled" else "Campaign activated for scheduler processing",
        "job_id": None,
        "status": campaign.status,
        "scheduled_for": campaign.send_start_time,
        "next_send_at": _campaign_next_run_hint(campaign),
    }


@router.post("/{campaign_id}/send-now")
async def send_campaign_now(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Immediately start sending emails for a campaign."""
    campaign = _get_owned_campaign(campaign_id, current_user.id, db)
    campaign.send_start_time = datetime.now(pytz.UTC)
    db.commit()
    _activate_campaign(campaign, db, force_send=True)
    result = send_campaign_emails(campaign.id, current_user.id, force_send=True)
    return {
        "message": "Campaign send-now batch processed",
        "job_id": None,
        "status": result["status"],
        "sent": result["sent"],
        "failed": result["failed"],
        "remaining": result["remaining"],
        "next_send_at": result.get("next_send_at"),
    }


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    campaign = _get_owned_campaign(campaign_id, current_user.id, db)
    campaign.status = "paused"
    campaign.next_send_at = None
    db.commit()
    db.refresh(campaign)
    return {
        "message": "Campaign paused",
        "status": campaign.status,
        "next_send_at": campaign.next_send_at,
    }


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    campaign = _get_owned_campaign(campaign_id, current_user.id, db)
    if campaign.status == "running":
        raise HTTPException(status_code=400, detail="Campaign is already running")

    pending_leads_count = db.query(Lead).filter(
        Lead.campaign_id == campaign.id,
        Lead.status == "pending",
        Lead.opted_out.is_(False),
    ).count()
    if pending_leads_count == 0:
        raise HTTPException(status_code=400, detail="Campaign has no pending leads to resume")

    campaign.status = "scheduled"
    campaign.next_send_at = None
    db.commit()
    db.refresh(campaign)
    return {
        "message": "Campaign resumed",
        "status": campaign.status,
        "next_send_at": _campaign_next_run_hint(campaign),
    }


@router.get("/{campaign_id}/job/{job_id}")
async def get_campaign_job_status(
    campaign_id: int,
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_owned_campaign(campaign_id, current_user.id, db)
    return {"id": job_id, "status": "not_applicable", "message": "Dedicated background jobs are disabled in scheduler mode."}


@router.delete("/{campaign_id}/job/{job_id}")
async def cancel_campaign_job(
    campaign_id: int,
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    campaign = _get_owned_campaign(campaign_id, current_user.id, db)
    campaign.status = "paused"
    db.commit()
    return {"message": "Campaign paused"}


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    campaign = _get_owned_campaign(campaign_id, current_user.id, db)
    db.query(EmailLog).filter(EmailLog.campaign_id == campaign_id).delete()
    db.query(Lead).filter(Lead.campaign_id == campaign_id).delete()
    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted successfully"}


@router.post("/{campaign_id}/leads")
async def create_manual_lead(
    campaign_id: int,
    payload: LeadManualCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_owned_campaign(campaign_id, current_user.id, db)

    existing = db.query(Lead).filter(
        Lead.campaign_id == campaign_id,
        Lead.email == payload.email,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A lead with this email already exists in the campaign")

    lead = Lead(
        campaign_id=campaign_id,
        email=payload.email,
        name=_normalize_lead_name(payload.name, payload.email),
        company=payload.company,
        title=payload.title,
        phone=payload.phone,
        website=payload.website,
        linkedin_url=payload.linkedin_url,
        location=payload.location,
        source=payload.source,
        notes=payload.notes,
        timezone=payload.timezone,
        priority=payload.priority,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return {"message": "Lead added successfully", "lead_id": lead.id}


@router.post("/{campaign_id}/leads/assign")
async def assign_leads_to_campaign(
    campaign_id: int,
    payload: LeadBulkAssignRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    source_campaign = _get_owned_campaign(campaign_id, current_user.id, db)
    target_campaign = _get_owned_campaign(payload.target_campaign_id, current_user.id, db)

    if source_campaign.id == target_campaign.id:
        raise HTTPException(status_code=400, detail="Source and target campaign must be different")

    leads = db.query(Lead).filter(
        Lead.campaign_id == source_campaign.id,
        Lead.id.in_(payload.lead_ids),
    ).all()

    target_emails = {
        email.lower()
        for (email,) in db.query(Lead.email).filter(Lead.campaign_id == target_campaign.id).all()
        if email
    }

    assigned = 0
    duplicates = 0
    for lead in leads:
        if lead.email.lower() in target_emails:
            duplicates += 1
            continue
        clone = Lead(
            campaign_id=target_campaign.id,
            email=lead.email,
            name=_normalize_lead_name(lead.name, lead.email),
            status="pending",
            company=lead.company,
            title=lead.title,
            phone=lead.phone,
            website=lead.website,
            linkedin_url=lead.linkedin_url,
            location=lead.location,
            source=lead.source,
            notes=lead.notes,
            custom_fields=lead.custom_fields,
            timezone=lead.timezone,
            priority=lead.priority,
            lifecycle_stage=lead.lifecycle_stage,
            lead_score=lead.lead_score,
            needs_follow_up=lead.needs_follow_up,
        )
        db.add(clone)
        target_emails.add(lead.email.lower())
        assigned += 1

    db.commit()
    return {
        "message": f"Assigned {assigned} leads to {target_campaign.name}",
        "assigned": assigned,
        "duplicates_skipped": duplicates,
    }


@router.delete("/{campaign_id}/leads")
async def delete_campaign_leads(
    campaign_id: int,
    payload: LeadBulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_owned_campaign(campaign_id, current_user.id, db)

    deleted = db.query(Lead).filter(
        Lead.campaign_id == campaign_id,
        Lead.id.in_(payload.lead_ids),
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": f"Deleted {deleted} leads", "deleted": deleted}


@router.patch("/{campaign_id}/leads/{lead_id}/stage")
async def update_lead_stage(
    campaign_id: int,
    lead_id: int,
    payload: LeadStageUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _get_owned_campaign(campaign_id, current_user.id, db)
    lead = db.query(Lead).filter(
        Lead.campaign_id == campaign_id,
        Lead.id == lead_id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.lifecycle_stage = payload.lifecycle_stage
    if payload.lifecycle_stage == "converted":
        lead.converted_at = datetime.now(pytz.UTC)
        lead.needs_follow_up = False
    elif payload.lifecycle_stage == "unsubscribed":
        lead.opted_out = True
        lead.opted_out_at = datetime.now(pytz.UTC)
    db.commit()
    return {"message": "Lead stage updated successfully"}
