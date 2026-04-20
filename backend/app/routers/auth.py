from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
import pytz
from ..database import get_db
from ..auth import get_oauth_url, exchange_code_for_token, create_or_update_user, generate_simple_token, get_current_user
from ..config import settings
from ..schemas import UserCreate, AccountSettingsUpdate
from ..models import EmailLog
from ..gmail_service import send_message

router = APIRouter()

@router.get("/login")
async def login(login_hint: str = ""):
    """Get OAuth2 login URL."""
    try:
        authorization_url, state = get_oauth_url(login_hint=login_hint or None)
        return {
            "authorization_url": authorization_url,
            "state": state
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth setup failed: {str(e)}")

@router.get("/callback")
async def oauth_callback(code: str, state: str, db: Session = Depends(get_db)):
    """Handle OAuth2 callback."""
    try:
        # Exchange code for token
        credentials = exchange_code_for_token(code)

        # Get user email from Gmail
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=credentials)
        profile = service.users().getProfile(userId='me').execute()
        email = profile['emailAddress']

        # For simplicity, we'll use email as google_id
        # In production, you'd get the actual Google user ID
        google_id = email

        # Create user data
        user_data = UserCreate(
            email=email,
            google_id=google_id,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            token_expiry=credentials.expiry
        )

        # Create or update user
        user = create_or_update_user(db, user_data)

        # Generate simple token
        token = generate_simple_token(user.id)

        # Redirect back to frontend with token
        redirect_url = f"{settings.FRONTEND_URL}/?auth_token={token}"
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {str(e)}")

@router.get("/me")
async def get_current_user_info(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user information."""
    today = datetime.now(pytz.UTC).date()
    sent_today = db.query(func.count(EmailLog.id)).filter(
        EmailLog.user_id == current_user.id,
        func.date(EmailLog.timestamp) == today,
        EmailLog.status != "failed"
    ).scalar() or 0

    return {
        "id": current_user.id,
        "email": current_user.email,
        "created_at": current_user.created_at,
        "daily_limit": current_user.custom_daily_limit or current_user.daily_limit or 30,
        "warmup_stage": current_user.warmup_stage or 0,
        "warmup_start_date": current_user.warmup_start_date,
        "timezone": current_user.timezone or "UTC",
        "sent_today": sent_today
    }

@router.post("/logout")
async def logout():
    """Stateless logout endpoint for UI parity."""
    return {"message": "Logged out successfully"}


@router.patch("/settings")
async def update_account_settings(
    payload: AccountSettingsUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if payload.daily_limit is not None:
        current_user.custom_daily_limit = max(1, payload.daily_limit)
    if payload.timezone:
        current_user.timezone = payload.timezone
    db.commit()
    return {"message": "Account settings updated successfully"}


@router.post("/test-send")
async def send_test_email(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    try:
        result = send_message(
            user=current_user,
            to=current_user.email,
            subject="SendFlow Test Send",
            body="This is a test email from your SendFlow account.",
        )
        return {
            "message": "Test email sent successfully",
            "message_id": result.get("id"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to send test email: {exc}")
