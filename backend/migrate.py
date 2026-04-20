"""
Migration script to update existing database with new columns for advanced email features.
Run this once to update the schema.
"""
from collections import defaultdict

from app.database import engine, SessionLocal
from app.models import User, Lead, EmailLog, Base
from sqlalchemy import inspect, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, JSON, text
from sqlalchemy.sql import func
import os


SUCCESSFUL_STATUSES = {"sent", "delivered", "read", "clicked", "replied", "bounced"}


def repair_historical_analytics_data():
    """Backfill lead analytics fields from existing email logs in an idempotent way."""
    db = SessionLocal()
    try:
        leads = db.query(Lead).all()
        if not leads:
            print("⏭️  No leads found for analytics repair")
            return

        logs = db.query(EmailLog).order_by(EmailLog.lead_id.asc(), EmailLog.timestamp.asc(), EmailLog.id.asc()).all()
        logs_by_lead = defaultdict(list)
        for log in logs:
            if log.lead_id:
                logs_by_lead[log.lead_id].append(log)

        repaired = 0
        for lead in leads:
            lead_logs = logs_by_lead.get(lead.id, [])
            if not lead_logs:
                continue

            successful_logs = [log for log in lead_logs if log.status in SUCCESSFUL_STATUSES]
            first_success = successful_logs[0].timestamp if successful_logs else None
            first_open = next((log.timestamp for log in lead_logs if log.status in {"read", "clicked", "replied"}), None)
            first_click = next((log.timestamp for log in lead_logs if log.status == "clicked"), None)
            first_reply = next((log.timestamp for log in lead_logs if log.status == "replied"), None)
            first_bounce = next((log.timestamp for log in lead_logs if log.status == "bounced"), None)
            last_success = successful_logs[-1].timestamp if successful_logs else None

            changed = False

            if first_success and lead.sent_at != first_success:
                lead.sent_at = first_success
                changed = True

            if first_open and lead.read_at != first_open:
                lead.read_at = first_open
                changed = True

            if first_click and lead.clicked_at != first_click:
                lead.clicked_at = first_click
                changed = True

            if first_reply and lead.replied_at != first_reply:
                lead.replied_at = first_reply
                changed = True

            if first_bounce and lead.bounced_at != first_bounce:
                lead.bounced_at = first_bounce
                changed = True

            if last_success and lead.last_contacted_at != last_success:
                lead.last_contacted_at = last_success
                changed = True

            derived_status = "pending"
            lifecycle_stage = "new"
            if lead.opted_out:
                derived_status = "opted_out"
                lifecycle_stage = "unsubscribed"
            elif first_reply:
                derived_status = "replied"
                lifecycle_stage = "replied"
            elif first_bounce:
                derived_status = "bounced"
                lifecycle_stage = "unsubscribed"
            elif first_click:
                derived_status = "clicked"
                lifecycle_stage = "contacted"
            elif first_open:
                derived_status = "read"
                lifecycle_stage = "opened"
            elif first_success:
                derived_status = "sent"
                lifecycle_stage = "contacted"

            if lead.status != derived_status:
                lead.status = derived_status
                changed = True

            if not lead.lifecycle_stage or lead.lifecycle_stage == "new" or changed:
                if lead.lifecycle_stage != lifecycle_stage:
                    lead.lifecycle_stage = lifecycle_stage
                    changed = True

            if changed:
                repaired += 1

        db.commit()
        print(f"✅ Repaired historical analytics for {repaired} leads")
    finally:
        db.close()

def migrate_database():
    """Update the database schema with missing columns for advanced email features."""
    inspector = inspect(engine)

    tables_to_columns = {
        'users': {
            'daily_limit': Integer,
            'warmup_stage': Integer,
            'warmup_start_date': DateTime,
            'timezone': String,
            'custom_daily_limit': Integer,
        },
        'campaigns': {
            'description': Text,
            'subject_template': String,
            'next_send_at': DateTime,
            'timezone': String,
            'hourly_send_rate': Integer,
            'min_delay_minutes': Integer,
            'max_delay_minutes': Integer,
            'send_window_start': String,
            'send_window_end': String,
            'send_window_weekdays_only': Boolean,
        },
        'leads': {
            'company': String,
            'title': String,
            'phone': String,
            'website': String,
            'linkedin_url': String,
            'location': String,
            'source': String,
            'notes': Text,
            'opted_out': Boolean,
            'opted_out_at': DateTime,
            'lifecycle_stage': String,
            'lead_score': Integer,
            'needs_follow_up': Boolean,
            'converted_at': DateTime,
        },
        'email_logs': {
            'message_id': String,
            'thread_id': String,
        },
    }

    indexes_to_create = {
        "daily_send_logs": [
            ("ix_daily_send_logs_user_id", ["user_id"]),
            ("ix_daily_send_logs_date", ["date"]),
        ],
        "sequences": [
            ("ix_sequences_user_id", ["user_id"]),
        ],
        "sequence_steps": [
            ("ix_sequence_steps_sequence_id", ["sequence_id"]),
        ],
        "sequence_enrollments": [
            ("ix_sequence_enrollments_lead_id", ["lead_id"]),
            ("ix_sequence_enrollments_sequence_id", ["sequence_id"]),
        ],
        "campaigns": [
            ("ix_campaigns_user_id", ["user_id"]),
            ("ix_campaigns_status", ["status"]),
            ("ix_campaigns_sequence_id", ["sequence_id"]),
        ],
        "leads": [
            ("ix_leads_campaign_id", ["campaign_id"]),
            ("ix_leads_status", ["status"]),
            ("ix_leads_campaign_status", ["campaign_id", "status"]),
        ],
        "email_logs": [
            ("ix_email_logs_user_id", ["user_id"]),
            ("ix_email_logs_campaign_id", ["campaign_id"]),
            ("ix_email_logs_lead_id", ["lead_id"]),
            ("ix_email_logs_status", ["status"]),
            ("ix_email_logs_timestamp", ["timestamp"]),
            ("ix_email_logs_lead_timestamp", ["lead_id", "timestamp"]),
        ],
    }

    with engine.connect() as conn:
        for table_name, columns in tables_to_columns.items():
            existing_columns = [col['name'] for col in inspector.get_columns(table_name)] if inspector.has_table(table_name) else []
            for col_name, col_type in columns.items():
                if col_name not in existing_columns:
                    if col_type == Integer:
                        if col_name == 'daily_limit':
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} INTEGER DEFAULT 30"))
                        elif col_name == 'hourly_send_rate':
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} INTEGER DEFAULT 5"))
                        else:
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} INTEGER DEFAULT 0"))
                    elif col_type == Boolean:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} BOOLEAN DEFAULT 0"))
                    elif col_type == DateTime:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} DATETIME"))
                    elif col_type == String:
                        if col_name == 'lifecycle_stage':
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} VARCHAR DEFAULT 'new'"))
                        elif col_name == 'timezone' and table_name == 'campaigns':
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} VARCHAR DEFAULT 'UTC'"))
                        else:
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} VARCHAR"))
                    elif col_type == Text:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} TEXT"))
                    print(f"✅ Added column: {table_name}.{col_name}")
                else:
                    print(f"⏭️  Column already exists: {table_name}.{col_name}")

        for table_name, indexes in indexes_to_create.items():
            if not inspector.has_table(table_name):
                continue
            for index_name, columns in indexes:
                column_list = ", ".join(columns)
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_list})"))
                print(f"✅ Ensured index: {index_name}")
        conn.commit()

    # Create any new tables defined by models
    Base.metadata.create_all(bind=engine)
    print("✅ All new tables created successfully")
    repair_historical_analytics_data()

if __name__ == "__main__":
    print("Starting database migration...")
    try:
        migrate_database()
        print("✅ Migration completed successfully!")
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
