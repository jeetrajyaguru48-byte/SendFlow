import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .database import get_db
from .models import User
from .schemas import UserCreate
from .config import settings

security = HTTPBearer()

def create_oauth_flow():
    """Create Google OAuth2 flow"""
    from google_auth_oauthlib.flow import Flow

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise ValueError("Google OAuth credentials are missing in .env")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )
    return flow

def get_oauth_url(login_hint: Optional[str] = None):
    """Generate OAuth2 authorization URL"""
    flow = create_oauth_flow()
    authorization_kwargs = {
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
    }
    if login_hint:
        authorization_kwargs["login_hint"] = login_hint

    authorization_url, state = flow.authorization_url(
        **authorization_kwargs
    )
    return authorization_url, state

def exchange_code_for_token(code: str):
    """Exchange authorization code for access token"""
    flow = create_oauth_flow()
    flow.fetch_token(code=code)
    return flow.credentials

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    token = credentials.credentials

    # For simplicity, we'll use a simple token validation
    # In production, you'd want proper JWT tokens
    try:
        user_id = int(token)
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        return user
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

def create_or_update_user(db: Session, user_data: UserCreate) -> User:
    """Create or update user in database"""
    user = db.query(User).filter(User.google_id == user_data.google_id).first()

    if user:
        # Update existing user
        user.email = user_data.email
        user.access_token = user_data.access_token
        if user_data.refresh_token:
            user.refresh_token = user_data.refresh_token
        user.token_expiry = user_data.token_expiry
    else:
        # Create new user
        user = User(
            email=user_data.email,
            google_id=user_data.google_id,
            access_token=user_data.access_token,
            refresh_token=user_data.refresh_token,
            token_expiry=user_data.token_expiry,
            timezone=settings.DEFAULT_TIMEZONE,
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    return user

def get_gmail_service(user: User):
    """Get Gmail API service for user"""
    creds = Credentials(
        token=user.access_token,
        refresh_token=user.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        expiry=user.token_expiry
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        # Update tokens in database
        from sqlalchemy.orm import Session
        db = next(get_db())
        user.access_token = creds.token
        user.token_expiry = creds.expiry
        db.commit()

    return build('gmail', 'v1', credentials=creds)

def generate_simple_token(user_id: int) -> str:
    """Generate a simple token for authentication (not secure for production)"""
    return str(user_id)
