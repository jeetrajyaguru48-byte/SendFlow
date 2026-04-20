from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# User schemas
class UserBase(BaseModel):
    email: str
    google_id: str

class UserCreate(UserBase):
    access_token: str
    refresh_token: Optional[str] = None
    token_expiry: Optional[datetime] = None

class User(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# Campaign schemas
class ScheduleEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    count: int = Field(..., ge=1)

class CampaignBase(BaseModel):
    name: str
    description: Optional[str] = None
    subject_template: Optional[str] = None
    message_template: str

class CampaignCreate(CampaignBase):
    is_sequence: bool = False
    sequence_id: Optional[int] = None
    ab_test_config: Optional[dict] = None
    send_schedule: Optional[List[ScheduleEntry]] = None
    send_start_time: Optional[datetime] = None  # When to start sending emails
    timezone: str = "UTC"
    hourly_send_rate: int = 5
    min_delay_minutes: Optional[int] = None
    max_delay_minutes: Optional[int] = None
    send_window_start: Optional[str] = "15:00"
    send_window_end: Optional[str] = "21:00"
    send_window_weekdays_only: bool = False

class Campaign(CampaignBase):
    id: int
    user_id: int
    status: str
    send_schedule: Optional[list]
    send_start_time: Optional[datetime]
    next_send_at: Optional[datetime]
    timezone: str = "UTC"
    hourly_send_rate: int = 5
    min_delay_minutes: Optional[int] = None
    max_delay_minutes: Optional[int] = None
    send_window_start: Optional[str] = None
    send_window_end: Optional[str] = None
    send_window_weekdays_only: bool = True
    emails_sent_in_batch: int = 0
    created_at: datetime
    updated_at: Optional[datetime]
    is_sequence: bool
    sequence_id: Optional[int]
    ab_test_config: Optional[dict]

    class Config:
        from_attributes = True

# Lead schemas
class LeadBase(BaseModel):
    email: str
    name: str
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    location: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None

class LeadCreate(LeadBase):
    campaign_id: int

class Lead(LeadBase):
    id: int
    campaign_id: int
    status: str
    company: Optional[str]
    title: Optional[str]
    phone: Optional[str]
    website: Optional[str]
    linkedin_url: Optional[str]
    location: Optional[str]
    source: Optional[str]
    notes: Optional[str]
    sent_at: Optional[datetime]
    read_at: Optional[datetime]
    clicked_at: Optional[datetime]
    bounced_at: Optional[datetime]
    replied_at: Optional[datetime]
    opted_out: bool = False
    custom_fields: Optional[dict]
    timezone: Optional[str]
    reply_category: Optional[str]
    last_contacted_at: Optional[datetime]
    priority: str
    lifecycle_stage: str = "new"
    lead_score: int = 0
    needs_follow_up: bool = False
    converted_at: Optional[datetime]

    class Config:
        from_attributes = True

# Sequence schemas
class SequenceBase(BaseModel):
    name: str
    description: Optional[str] = None

class SequenceCreate(SequenceBase):
    pass

class SequenceStepBase(BaseModel):
    step_number: int
    subject: str
    body: str
    delay_hours: int = 0
    sender_name: Optional[str] = None
    priority: str = "normal"
    send_window_start: Optional[str] = None
    send_window_end: Optional[str] = None
    weekdays_only: bool = True

class SequenceStepCreate(SequenceStepBase):
    sequence_id: int

class SequenceStep(SequenceStepBase):
    id: int
    sequence_id: int

    class Config:
        from_attributes = True

class Sequence(SequenceBase):
    id: int
    user_id: int
    created_at: datetime
    steps: List[SequenceStep] = []

    class Config:
        from_attributes = True

# API request/response schemas
class UploadLeadsRequest(BaseModel):
    campaign_id: int
    leads: List[LeadBase]

class LeadImportPreviewRequest(BaseModel):
    headers: List[str]

class LeadImportConfirmRequest(BaseModel):
    campaign_id: int
    rows: List[dict]
    mapping: dict

class LeadBulkAssignRequest(BaseModel):
    lead_ids: List[int]
    target_campaign_id: int

class LeadBulkDeleteRequest(BaseModel):
    lead_ids: List[int]

class LeadStageUpdateRequest(BaseModel):
    lifecycle_stage: str

class LeadManualCreateRequest(BaseModel):
    email: str
    name: str
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    location: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    timezone: Optional[str] = None
    priority: str = "normal"

class InboxReplyRequest(BaseModel):
    thread_id: str
    to_email: str
    subject: str
    body: str

class AccountSettingsUpdate(BaseModel):
    daily_limit: Optional[int] = None
    timezone: Optional[str] = None

class SendCampaignRequest(BaseModel):
    campaign_id: int

class TrackingPixelResponse(BaseModel):
    message: str

class ClickRedirectResponse(BaseModel):
    redirect_url: str

# Analytics schemas
class CampaignStats(BaseModel):
    total_leads: int
    sent: int
    read: int
    clicked: int
    bounced: int
    replied: int

class LeadStatus(BaseModel):
    id: int
    email: str
    name: str
    status: str
    company: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    location: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    custom_fields: Optional[dict] = None
    priority: str = "normal"
    reply_category: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    opted_out: bool = False
    lifecycle_stage: str = "new"
    lead_score: int = 0
    needs_follow_up: bool = False
    converted_at: Optional[datetime] = None
    sent_at: Optional[datetime]
    read_at: Optional[datetime]
    clicked_at: Optional[datetime]
    bounced_at: Optional[datetime]
    replied_at: Optional[datetime]
    next_send_at: Optional[datetime] = None
    send_status: str = "Not scheduled"  # "Not scheduled", "Scheduled", "Sending soon", "Paused", "Completed"
    last_event_type: Optional[str] = None
    last_event_at: Optional[datetime] = None
    email_history: List[dict] = []
