import base64
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate, make_msgid
from typing import Dict, List, Optional
import re
import json
import os
import time
from datetime import datetime
from .auth import get_gmail_service
from .models import Campaign, EmailLog, Lead, User
from .config import settings

def _sanitize_subject(subject: str) -> str:
    subject = re.sub(r"\s+", " ", subject).strip()
    subject = re.sub(r"\b(urgent|buy now|free|act now|order now|limited time)\b", "", subject, flags=re.IGNORECASE)
    return subject[:78]


def _sanitize_body(message_text: str) -> str:
    normalized = (message_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "\n".join(line.rstrip() for line in normalized.split("\n"))


def _looks_like_html(content: str) -> bool:
    return bool(re.search(r"<(a|p|br|div|span|img|html|body)\b", content or "", flags=re.IGNORECASE))


def _render_plain_text_as_html(message_text: str) -> str:
    normalized = _sanitize_body(message_text)
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    rendered = []
    for paragraph in paragraphs:
        safe_paragraph = html.escape(paragraph).replace("\n", "<br>")
        rendered.append(
            f'<p style="margin:0 0 16px;line-height:1.7;color:#111827;font-size:15px;">{safe_paragraph}</p>'
        )
    return "".join(rendered)


def _html_to_text(html_content: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", html_content)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(
        r'(?is)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        lambda match: f"{re.sub(r'<[^>]+>', '', match.group(2)).strip()} ({match.group(1)})",
        text,
    )
    text = re.sub(r"(?is)<img[^>]*>", "", text)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_PROFILE_CACHE: Dict[int, tuple[str, float]] = {}
_PROFILE_CACHE_TTL_SECONDS = 10 * 60


def _get_authenticated_sender_email(service, user_id: int) -> str:
    now = time.time()
    cached = _PROFILE_CACHE.get(user_id)
    if cached and (now - cached[1]) < _PROFILE_CACHE_TTL_SECONDS:
        return cached[0]
    profile = service.users().getProfile(userId="me").execute()
    email_address = (profile.get("emailAddress") or "").strip().lower()
    _PROFILE_CACHE[user_id] = (email_address, now)
    return email_address


def create_message(
    sender_email: str,
    to: str,
    subject: str,
    message_text: str,
    *,
    sender_name: Optional[str] = None,
    unsubscribe_link: Optional[str] = None,
    unsubscribe_mailto: Optional[str] = None,
) -> Dict:
    """Create a message for an email."""
    from_value = formataddr((sender_name, sender_email)) if sender_name else sender_email
    sanitized_body = _sanitize_body(message_text)

    if settings.EMAIL_PREFER_PLAIN_TEXT:
        if _looks_like_html(sanitized_body):
            text_content = _html_to_text(sanitized_body)
        else:
            text_content = sanitized_body
        message = MIMEText(text_content, "plain", "utf-8")
    else:
        message = MIMEMultipart("alternative")

    message["To"] = to
    message["From"] = from_value
    message["Subject"] = _sanitize_subject(subject)
    message["Reply-To"] = from_value
    message["Date"] = formatdate(localtime=True)
    try:
        sender_domain = sender_email.split("@", 1)[1]
    except Exception:
        sender_domain = None
    message["Message-ID"] = make_msgid(domain=sender_domain)
    list_unsubscribe_entries: List[str] = []
    if unsubscribe_mailto:
        list_unsubscribe_entries.append(f"<mailto:{unsubscribe_mailto}?subject=unsubscribe>")
    if unsubscribe_link:
        list_unsubscribe_entries.append(f"<{unsubscribe_link}>")
    if list_unsubscribe_entries:
        message["List-Unsubscribe"] = ", ".join(list_unsubscribe_entries)
        if unsubscribe_link:
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    if not settings.EMAIL_PREFER_PLAIN_TEXT:
        if _looks_like_html(sanitized_body):
            inner_html = sanitized_body
            text_content = _html_to_text(sanitized_body)
        else:
            inner_html = _render_plain_text_as_html(sanitized_body)
            text_content = sanitized_body

        html_content = f"""
        <html>
          <body style="margin:0;padding:24px;background-color:#f8fafc;font-family:Arial,sans-serif;">
            <div style="max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;padding:32px;">
              {inner_html}
            </div>
          </body>
        </html>
        """

        message.attach(MIMEText(text_content, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw_message}

def send_message_dev(user: User, to: str, subject: str, body: str, unsubscribe_link: Optional[str] = None) -> Dict:
    """Send an email in development mode (logs to file, doesn't actually send)."""
    import uuid
    import hashlib
    
    message_id = str(uuid.uuid4())
    
    # Create test inbox directory
    os.makedirs(settings.TEST_EMAIL_INBOX, exist_ok=True)
    
    # Generate a file hash for the message
    file_hash = hashlib.md5(f"{to}_{datetime.now().isoformat()}".encode()).hexdigest()[:8]
    email_file = os.path.join(settings.TEST_EMAIL_INBOX, f"{to}_{file_hash}.json")
    
    # Log the email
    email_record = {
        "message_id": message_id,
        "from": user.email,
        "to": to,
        "subject": subject,
        "body": body[:500],  # First 500 chars
        "timestamp": datetime.now().isoformat(),
        "unsubscribe_link": unsubscribe_link
    }
    
    with open(email_file, 'w') as f:
        json.dump(email_record, f, indent=2)
    
    print(f"📧 [DEV MODE] Email sent to {to}")
    print(f"   Subject: {subject[:50]}...")
    print(f"   Saved to: {email_file}")
    
    return {"id": message_id, "threadId": message_id}

def send_message(
    user: User,
    to: str,
    subject: str,
    body: str,
    unsubscribe_link: Optional[str] = None,
    sender_name: Optional[str] = None,
    unsubscribe_mailto: Optional[str] = None,
) -> Dict:
    """Send an email message."""
    # Use dev mode if enabled
    if settings.DEV_MODE:
        return send_message_dev(user, to, subject, body, unsubscribe_link)
    
    try:
        service = get_gmail_service(user)
        authenticated_email = _get_authenticated_sender_email(service, user.id)
        if authenticated_email and authenticated_email.lower() != (user.email or "").strip().lower():
            raise Exception(
                f"Connected sender mismatch: expected {user.email}, but Google authenticated {authenticated_email}. "
                "Reconnect the correct Google account."
            )

        message = create_message(
            user.email,
            to,
            subject,
            body,
            sender_name=sender_name,
            unsubscribe_link=unsubscribe_link,
            unsubscribe_mailto=unsubscribe_mailto,
        )

        sent_message = service.users().messages().send(
            userId='me',
            body=message
        ).execute()

        return {
            "id": sent_message["id"],
            "threadId": sent_message.get("threadId"),
        }
    except Exception as e:
        raise Exception(f"Failed to send email: {str(e)}")

def get_message(user: User, message_id: str) -> Dict:
    """Get a specific message."""
    service = get_gmail_service(user)
    return service.users().messages().get(userId='me', id=message_id).execute()

def list_messages(user: User, query: str = "", max_results: int = 100) -> List[Dict]:
    """List messages matching query."""
    service = get_gmail_service(user)
    results = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=max_results
    ).execute()

    messages = results.get('messages', [])
    return messages


def _get_headers_map(headers: List[Dict]) -> Dict[str, str]:
    return {header["name"].lower(): header["value"] for header in headers}


def _decode_html_payload(message: Dict) -> str:
    try:
        payload = message.get("payload", {})

        def find_body(part: Dict) -> Optional[str]:
            mime_type = part.get("mimeType")
            body = part.get("body", {})
            data = body.get("data")
            if data and mime_type in {"text/plain", "text/html"}:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            for child in part.get("parts", []) or []:
                nested = find_body(child)
                if nested:
                    return nested
            return None

        return find_body(payload) or ""
    except Exception:
        return ""


def get_inbox_threads(user: User, db, max_results: int = 25) -> List[Dict]:
    """Return inbox messages enriched with sender, subject, thread, and campaign context."""
    service = get_gmail_service(user)
    results = service.users().messages().list(
        userId="me",
        q="in:inbox",
        maxResults=max_results,
    ).execute()

    messages = results.get("messages", [])
    threads: List[Dict] = []

    for message_ref in messages:
        message = service.users().messages().get(
            userId="me",
            id=message_ref["id"],
            format="full",
        ).execute()
        headers = _get_headers_map(message.get("payload", {}).get("headers", []))
        thread_id = message.get("threadId")

        matching_logs = db.query(EmailLog).filter(EmailLog.thread_id == thread_id).all()
        if not matching_logs:
            thread = service.users().threads().get(userId="me", id=thread_id).execute()
            thread_message_ids = [item["id"] for item in thread.get("messages", [])]
            if thread_message_ids:
                matching_logs = db.query(EmailLog).filter(EmailLog.message_id.in_(thread_message_ids)).all()

        primary_log = matching_logs[0] if matching_logs else None
        lead = primary_log.lead if primary_log else None
        campaign = primary_log.campaign if primary_log else None

        reply_body = extract_message_content(message) or _decode_html_payload(message) or message.get("snippet", "")
        reply_category = categorize_reply(reply_body)

        threads.append({
            "id": message.get("id"),
            "thread_id": thread_id,
            "subject": headers.get("subject") or "(No subject)",
            "from_name": headers.get("from", "").split("<")[0].strip().strip('"') or headers.get("from", ""),
            "from_email": headers.get("from", ""),
            "snippet": message.get("snippet", ""),
            "received_at": datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000).isoformat() if message.get("internalDate") else None,
            "body": reply_body,
            "campaign_id": campaign.id if campaign else None,
            "campaign_name": campaign.name if campaign else None,
            "lead_id": lead.id if lead else None,
            "lead_email": lead.email if lead else None,
            "reply_category": reply_category,
            "needs_follow_up": lead.needs_follow_up if lead else False,
            "converted": lead.lifecycle_stage == "converted" if lead else False,
        })

    return threads


def send_reply_message(user: User, thread_id: str, to_email: str, subject: str, body: str) -> Dict:
    """Send a threaded reply using Gmail."""
    service = get_gmail_service(user)
    message = MIMEText(body, "plain")
    message["To"] = to_email
    message["From"] = user.email
    message["Subject"] = _sanitize_subject(subject if subject.lower().startswith("re:") else f"Re: {subject}")

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    payload = {
        "raw": raw_message,
        "threadId": thread_id,
    }
    return service.users().messages().send(userId="me", body=payload).execute()

def check_for_bounces_and_replies(user: User, original_message_id: str) -> Dict:
    """Check if original message has bounces or replies with categorization."""
    try:
        service = get_gmail_service(user)

        # Get the original message to find thread
        original_message = service.users().messages().get(
            userId='me', id=original_message_id
        ).execute()

        thread_id = original_message['threadId']

        # Get all messages in the thread
        thread = service.users().threads().get(userId='me', id=thread_id).execute()
        messages = thread['messages']

        has_reply = len(messages) > 1
        has_bounce = False
        reply_category = None
        reply_content = None

        # Check for bounce messages
        for message in messages:
            headers = {h['name'].lower(): h['value'] for h in message['payload']['headers']}

            # Check for bounce indicators
            if ('delivery-status' in headers.get('content-type', '').lower() or
                'mail delivery' in headers.get('subject', '').lower() or
                'failure' in headers.get('subject', '').lower()):
                has_bounce = True
                break

        # Analyze replies
        if has_reply:
            # Get the latest reply (excluding original)
            reply_messages = [msg for msg in messages if msg['id'] != original_message_id]
            if reply_messages:
                latest_reply = reply_messages[-1]  # Most recent reply
                
                # Extract reply content
                reply_content = extract_message_content(latest_reply)
                reply_category = categorize_reply(reply_content)

        return {
            'has_reply': has_reply,
            'has_bounce': has_bounce,
            'reply_category': reply_category,
            'reply_content': reply_content
        }

    except Exception as e:
        print(f"Error checking bounces/replies: {str(e)}")
        return {
            'has_reply': False, 
            'has_bounce': False,
            'reply_category': None,
            'reply_content': None
        }

def extract_message_content(message: Dict) -> str:
    """Extract plain text content from a Gmail message."""
    try:
        payload = message['payload']
        
        def get_text_part(parts):
            for part in parts:
                if part['mimeType'] == 'text/plain':
                    if 'data' in part['body']:
                        return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                elif 'parts' in part:
                    text = get_text_part(part['parts'])
                    if text:
                        return text
            return None
        
        if 'parts' in payload:
            return get_text_part(payload['parts']) or ""
        elif payload['mimeType'] == 'text/plain' and 'data' in payload['body']:
            return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        
        return ""
    except Exception as e:
        print(f"Error extracting message content: {str(e)}")
        return ""

def categorize_reply(reply_content: str) -> str:
    """Categorize a reply using simple rule-based analysis."""
    if not reply_content:
        return "unknown"
    
    content_lower = reply_content.lower()
    
    # Interested signals
    interested_keywords = [
        'interested', 'yes', 'great', 'awesome', 'let\'s', 'schedule', 'meeting', 
        'call', 'talk', 'discuss', 'tell me more', 'how does it work', 'price',
        'cost', 'budget', 'when can we', 'next steps'
    ]
    
    # Not interested signals
    not_interested_keywords = [
        'not interested', 'no thanks', 'unsubscribe', 'remove me', 'stop',
        'no longer', 'not right', 'not a fit', 'not for me', 'pass'
    ]
    
    # Out of office signals
    ooo_keywords = [
        'out of office', 'ooo', 'vacation', 'holiday', 'away', 'autoreply',
        'automatic reply', 'not in the office', 'returning'
    ]
    
    # Referral signals
    referral_keywords = [
        'refer', 'know someone', 'contact someone', 'pass along', 'forward',
        'someone else', 'different person', 'wrong person'
    ]
    
    # Check for interested
    if any(keyword in content_lower for keyword in interested_keywords):
        return "interested"
    
    # Check for not interested
    if any(keyword in content_lower for keyword in not_interested_keywords):
        return "not_interested"
    
    # Check for out of office
    if any(keyword in content_lower for keyword in ooo_keywords):
        return "out_of_office"
    
    # Check for referral
    if any(keyword in content_lower for keyword in referral_keywords):
        return "referral"
    
    # Default to unknown
    return "unknown"

def get_user_email_address(user: User) -> str:
    """Get the user's email address from Gmail profile."""
    try:
        service = get_gmail_service(user)
        profile = service.users().getProfile(userId='me').execute()
        return profile['emailAddress']
    except Exception as e:
        raise Exception(f"Failed to get user email: {str(e)}")

def search_messages(user: User, query: str, max_results: int = 50) -> List[Dict]:
    """Search for messages with specific query."""
    return list_messages(user, query=query, max_results=max_results)
