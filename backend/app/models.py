from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    google_id = Column(String, unique=True, index=True)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expiry = Column(DateTime)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # New fields for send limits and warm-up
    daily_limit = Column(Integer, default=30)
    warmup_stage = Column(Integer, default=0)  # 0 = not warming up, 1-6 = stages (5,10,15,20,25,30)
    warmup_start_date = Column(DateTime(timezone=True), nullable=True)
    timezone = Column(String, default="UTC")
    custom_daily_limit = Column(Integer, nullable=True)

    campaigns = relationship("Campaign", back_populates="user")
    email_logs = relationship("EmailLog", back_populates="user")
    sequences = relationship("Sequence", back_populates="user")
    daily_sends = relationship("DailySendLog", back_populates="user")

class DailySendLog(Base):
    __tablename__ = "daily_send_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    date = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    emails_sent = Column(Integer, default=0)
    emails_queued = Column(Integer, default=0)

    user = relationship("User", back_populates="daily_sends")

class Sequence(Base):
    __tablename__ = "sequences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="sequences")
    steps = relationship("SequenceStep", back_populates="sequence", order_by="SequenceStep.step_number")
    enrollments = relationship("SequenceEnrollment", back_populates="sequence")
    campaigns = relationship("Campaign", back_populates="sequence")

class SequenceStep(Base):
    __tablename__ = "sequence_steps"

    id = Column(Integer, primary_key=True, index=True)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), index=True)
    step_number = Column(Integer)
    subject = Column(String)
    body = Column(Text)
    delay_hours = Column(Integer, default=0)
    sender_name = Column(String, nullable=True)
    priority = Column(String, default="normal")  # high, normal, low
    send_window_start = Column(String, nullable=True)  # e.g. "09:00"
    send_window_end = Column(String, nullable=True)    # e.g. "17:00"
    weekdays_only = Column(Boolean, default=True)

    sequence = relationship("Sequence", back_populates="steps")
    email_logs = relationship("EmailLog", back_populates="sequence_step")

class SequenceEnrollment(Base):
    __tablename__ = "sequence_enrollments"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), index=True)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), index=True)
    current_step = Column(Integer, default=1)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())
    paused_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    next_send_at = Column(DateTime(timezone=True), nullable=True)

    lead = relationship("Lead", back_populates="sequence_enrollments")
    sequence = relationship("Sequence", back_populates="enrollments")

class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String)
    description = Column(Text, nullable=True)
    subject_template = Column(String, nullable=True)
    message_template = Column(Text)
    status = Column(String, default="draft", index=True)  # draft, scheduled, queued, running, completed, paused, failed
    send_schedule = Column(JSON, nullable=True)
    send_start_time = Column(DateTime(timezone=True), nullable=True)  # When to start sending
    timezone = Column(String, default="UTC")
    hourly_send_rate = Column(Integer, default=5)
    min_delay_minutes = Column(Integer, nullable=True)
    max_delay_minutes = Column(Integer, nullable=True)
    send_window_start = Column(String, nullable=True)
    send_window_end = Column(String, nullable=True)
    send_window_weekdays_only = Column(Boolean, default=True)
    emails_sent_in_batch = Column(Integer, default=0)  # Track emails sent for this batch
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # New fields for sequences and A/B testing
    is_sequence = Column(Boolean, default=False)
    sequence_id = Column(Integer, ForeignKey("sequences.id"), nullable=True, index=True)
    ab_test_config = Column(JSON, nullable=True)  # {"enabled": true, "variants": [...], "sample_size": 50}

    user = relationship("User", back_populates="campaigns")
    leads = relationship("Lead", back_populates="campaign")
    email_logs = relationship("EmailLog", back_populates="campaign")
    sequence = relationship("Sequence", back_populates="campaigns")

class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    email = Column(String, index=True)
    name = Column(String)
    status = Column(String, default="pending", index=True)  # pending, sent, read, clicked, bounced, replied, opted_out
    company = Column(String, nullable=True)
    title = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    website = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    location = Column(String, nullable=True)
    source = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    clicked_at = Column(DateTime(timezone=True), nullable=True)
    bounced_at = Column(DateTime(timezone=True), nullable=True)
    replied_at = Column(DateTime(timezone=True), nullable=True)
    opted_out = Column(Boolean, default=False)
    opted_out_at = Column(DateTime(timezone=True), nullable=True)
    
    # New fields for personalization and tracking
    custom_fields = Column(JSON, nullable=True)  # {"first_name": "John", "company": "Acme", "role": "CEO"}
    timezone = Column(String, nullable=True)
    reply_category = Column(String, nullable=True)  # interested, not_interested, out_of_office, referral
    last_contacted_at = Column(DateTime(timezone=True), nullable=True)
    priority = Column(String, default="normal")  # high, normal, low
    lifecycle_stage = Column(String, default="new")  # new, contacted, opened, replied, converted, unsubscribed
    lead_score = Column(Integer, default=0)
    needs_follow_up = Column(Boolean, default=False)
    converted_at = Column(DateTime(timezone=True), nullable=True)

    campaign = relationship("Campaign", back_populates="leads")
    email_logs = relationship("EmailLog", back_populates="lead")
    sequence_enrollments = relationship("SequenceEnrollment", back_populates="lead")

class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), index=True)
    tracking_id = Column(String, unique=True, index=True)
    message_id = Column(String, nullable=True)
    thread_id = Column(String, nullable=True, index=True)
    subject = Column(String)
    body = Column(Text)
    status = Column(String, index=True)  # sent, delivered, read, clicked, bounced, replied
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    error_message = Column(Text, nullable=True)
    
    # New fields for A/B testing and sequences
    variant = Column(String, nullable=True)  # A, B, C for A/B testing
    sequence_step_id = Column(Integer, ForeignKey("sequence_steps.id"), nullable=True)

    user = relationship("User", back_populates="email_logs")
    campaign = relationship("Campaign", back_populates="email_logs")
    lead = relationship("Lead", back_populates="email_logs")
    sequence_step = relationship("SequenceStep", back_populates="email_logs")
