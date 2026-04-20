import secrets
import html
import re
from datetime import datetime, timezone
from fastapi import HTTPException, Response
from sqlalchemy.orm import Session
from .models import EmailLog, Lead
from .database import SessionLocal

def generate_tracking_id() -> str:
    """Generate a unique tracking ID for emails."""
    return secrets.token_urlsafe(16)

def track_email_open(tracking_id: str):
    """Track when an email is opened via tracking pixel."""
    db: Session = SessionLocal()
    try:
        # Find the email log by tracking ID
        email_log = db.query(EmailLog).filter(EmailLog.tracking_id == tracking_id).first()

        if email_log:
            # Update email log status
            if email_log.status == "sent":
                email_log.status = "read"

            # Update lead status
            lead = db.query(Lead).filter(Lead.id == email_log.lead_id).first()
            if lead and lead.status in {"sent", "read"}:
                first_open = lead.read_at is None
                lead.status = "read"
                lead.read_at = datetime.now(timezone.utc)
                lead.lifecycle_stage = "opened"
                if first_open:
                    lead.lead_score = (lead.lead_score or 0) + 5

            db.commit()

    except Exception as e:
        print(f"Error tracking email open: {str(e)}")
    finally:
        db.close()

def track_link_click(tracking_id: str, redirect_url: str):
    """Track when a link is clicked and redirect."""
    db: Session = SessionLocal()
    try:
        # Find the email log by tracking ID
        email_log = db.query(EmailLog).filter(EmailLog.tracking_id == tracking_id).first()

        if email_log:
            # Update email log status
            email_log.status = "clicked"

            # Update lead status
            lead = db.query(Lead).filter(Lead.id == email_log.lead_id).first()
            if lead and (lead.status == "sent" or lead.status == "read"):
                lead.status = "clicked"
                lead.clicked_at = datetime.now(timezone.utc)
                lead.lead_score = (lead.lead_score or 0) + 10

            db.commit()

    except Exception as e:
        print(f"Error tracking link click: {str(e)}")
    finally:
        db.close()

    # Return redirect response
    return redirect_url

def get_tracking_pixel(tracking_id: str):
    """Return a 1x1 transparent PNG tracking pixel."""
    # Create a minimal 1x1 transparent PNG
    pixel_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82'

    # Track the open
    track_email_open(tracking_id)

    return Response(content=pixel_data, media_type="image/png")

def wrap_link_with_tracking(original_url: str, tracking_id: str, base_url: str) -> str:
    """Wrap a URL with click tracking."""
    from urllib.parse import quote
    encoded_url = quote(original_url, safe='')
    return f"{base_url}/track/click/{tracking_id}?url={encoded_url}"

def process_message_with_tracking(message: str, tracking_id: str, base_url: str) -> str:
    """Convert plain-text email body into tracked HTML while preserving formatting."""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    normalized = (message or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    rendered_parts = []
    cursor = 0
    for match in re.finditer(url_pattern, normalized):
        rendered_parts.append(html.escape(normalized[cursor:match.start()]))
        url = match.group(0)
        tracked_url = wrap_link_with_tracking(url, tracking_id, base_url)
        rendered_parts.append(
            f'<a href="{tracked_url}" style="color:#2563eb;text-decoration:underline;">{html.escape(url)}</a>'
        )
        cursor = match.end()
    rendered_parts.append(html.escape(normalized[cursor:]))

    html_body = "".join(rendered_parts)
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", html_body) if block.strip()]
    if not paragraphs:
        paragraphs = [html_body.replace("\n", "<br>")]
    else:
        paragraphs = [paragraph.replace("\n", "<br>") for paragraph in paragraphs]

    tracked_message = "".join(
        f'<p style="margin:0 0 16px;line-height:1.7;color:#111827;font-size:15px;">{paragraph}</p>'
        for paragraph in paragraphs
    )

    tracking_pixel = f'<img src="{base_url}/track/pixel/{tracking_id}" width="1" height="1" alt="" style="width:1px;height:1px;opacity:0;border:0;" />'
    return f"{tracked_message}{tracking_pixel}"
