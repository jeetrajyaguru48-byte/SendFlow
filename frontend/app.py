import pandas as pd
import requests
import streamlit as st
from datetime import datetime, date, time, timezone

import pytz

# Configuration
API_BASE_URL = "http://localhost:8000"


def init_state():
    if "accounts" not in st.session_state:
        st.session_state.accounts = []
    if "active_account_id" not in st.session_state:
        st.session_state.active_account_id = None
    if "selected_campaign" not in st.session_state:
        st.session_state.selected_campaign = None
    if "accounts_restored" not in st.session_state:
        st.session_state.accounts_restored = False


def get_active_account():
    for account in st.session_state.accounts:
        if account["id"] == st.session_state.active_account_id:
            return account
    return None


def get_active_token():
    account = get_active_account()
    return account["token"] if account else None


def api_request(method, endpoint, data=None, files=None, token=None):
    """Make API request with authentication."""
    headers = {}
    auth_token = token or get_active_token()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    url = f"{API_BASE_URL}{endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            if files:
                response = requests.post(url, headers=headers, data=data, files=files)
            else:
                response = requests.post(url, headers=headers, json=data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")

        return response
    except requests.exceptions.RequestException as e:
        st.error(f"Connection error: {str(e)}")
        return None


def upsert_account(user, token):
    account = {
        "id": user["id"],
        "email": user["email"],
        "token": token,
        "created_at": user.get("created_at"),
        "daily_limit": user.get("daily_limit", 30),
        "timezone": user.get("timezone", "UTC"),
    }
    st.session_state.accounts = [a for a in st.session_state.accounts if a["id"] != account["id"]]
    st.session_state.accounts.append(account)
    st.session_state.accounts = sorted(st.session_state.accounts, key=lambda a: a["email"])
    st.session_state.active_account_id = account["id"]


def persist_accounts_to_query_params():
    tokens = [str(account["token"]) for account in st.session_state.accounts]
    active_id = str(st.session_state.active_account_id) if st.session_state.active_account_id is not None else ""
    params = {}
    if tokens:
        params["auth_token"] = tokens
    if active_id:
        params["active_account_id"] = active_id
    st.experimental_set_query_params(**params)


def restore_accounts_from_query_params():
    if st.session_state.accounts_restored:
        return

    query_params = st.experimental_get_query_params()
    tokens = query_params.get("auth_token", [])
    active_account_id = query_params.get("active_account_id", [None])[0]

    restored_accounts = []
    for token in tokens:
        user_resp = api_request("GET", "/auth/me", token=token)
        if user_resp and user_resp.status_code == 200:
            user = user_resp.json()
            restored_accounts.append({
                "id": user["id"],
                "email": user["email"],
                "token": token,
                "created_at": user.get("created_at"),
                "daily_limit": user.get("daily_limit", 30),
                "timezone": user.get("timezone", "UTC"),
            })

    if restored_accounts:
        st.session_state.accounts = restored_accounts
        if active_account_id and active_account_id.isdigit():
            active_id = int(active_account_id)
            if any(account["id"] == active_id for account in restored_accounts):
                st.session_state.active_account_id = active_id
            else:
                st.session_state.active_account_id = restored_accounts[0]["id"]
        else:
            st.session_state.active_account_id = restored_accounts[0]["id"]

    st.session_state.accounts_restored = True


def handle_auth_callback():
    query_params = st.experimental_get_query_params()
    if "auth_token" in query_params:
        for token in query_params["auth_token"]:
            user_resp = api_request("GET", "/auth/me", token=token)
            if user_resp and user_resp.status_code == 200:
                upsert_account(user_resp.json(), token)

        if st.session_state.accounts:
            persist_accounts_to_query_params()


def login_page():
    """Display login page."""
    st.title("📧 Email Automation Platform")
    st.subheader("Login with Google")
    st.markdown(
        "Connect one or more Gmail accounts, run scheduled campaigns or send instantly, "
        "and view detailed lead information from the same app."
    )

    response = api_request("GET", "/auth/login")
    if response and response.status_code == 200:
        auth_url = response.json()["authorization_url"]
        st.link_button("🔐 Login with Gmail", auth_url, use_container_width=False)
    else:
        st.error("Failed to get login URL. Check backend connection.")


def render_account_switcher():
    if not st.session_state.accounts:
        return

    account = get_active_account()
    selected_email = st.selectbox(
        "Connected Accounts",
        options=[a["email"] for a in st.session_state.accounts],
        index=[a["id"] for a in st.session_state.accounts].index(account["id"]) if account else 0,
    )
    selected_account = next(a for a in st.session_state.accounts if a["email"] == selected_email)
    st.session_state.active_account_id = selected_account["id"]
    persist_accounts_to_query_params()

    add_response = api_request("GET", "/auth/login")
    if add_response and add_response.status_code == 200:
        st.link_button("➕ Add Another Google Account", add_response.json()["authorization_url"])


def campaign_manager():
    """Display campaign management interface."""
    st.markdown("# 📈 Campaign Manager")
    st.markdown(
        "Use the tabs below to create campaigns, schedule them, send instantly, upload leads, "
        "and manage campaigns from different connected email accounts."
    )

    with st.expander("Quick setup steps"):
        st.markdown(
            "1. Create a campaign with subject, message, and optional scheduled start time.\n"
            "2. Upload a CSV with emails, names, and extra lead details.\n"
            "3. Start the campaign instantly or let it begin at the scheduled time.\n"
            "4. Review lead-level details in Lead Intelligence."
        )

    tab1, tab2, tab3, tab4 = st.tabs(["Create Campaign", "My Campaigns", "Upload Leads", "Connected Accounts"])

    with tab1:
        st.subheader("Create New Campaign")

        with st.form("campaign_form"):
            campaign_name = st.text_input("Campaign Name")
            subject_template = st.text_input(
                "Subject Template",
                help="Use tags like {name}, {first_name}, {company}"
            )
            campaign_notes = st.text_area("Campaign Notes", height=100)
            message_template = st.text_area(
                "Message Template",
                height=220,
                help="Use {name}, {first_name}, {last_name}, {email}, and CSV custom fields."
            )

            st.markdown("### Timing & Delivery")
            st.info(
                "All campaigns follow a fixed sending policy: 30 emails per day, evenly spaced, between 3:00 PM and 9:00 PM IST."
            )
            schedule_enabled = st.checkbox("Schedule campaign start", value=False)
            if schedule_enabled:
                scheduled_date = st.date_input("Scheduled Date", value=date.today())
                scheduled_time = st.time_input("Scheduled Time", value=time(9, 0))
            else:
                scheduled_date = None
                scheduled_time = None

            if st.form_submit_button("Create Campaign"):
                if campaign_name and message_template:
                    send_start_time = None
                    if schedule_enabled and scheduled_date and scheduled_time:
                        account = get_active_account() or {}
                        tz_name = account.get("timezone") or "Asia/Kolkata"
                        tz = pytz.timezone(tz_name)
                        local_dt = tz.localize(datetime.combine(scheduled_date, scheduled_time))
                        send_start_time = local_dt.astimezone(timezone.utc).isoformat()

                    response = api_request("POST", "/campaigns/", {
                        "name": campaign_name,
                        "description": campaign_notes,
                        "subject_template": subject_template,
                        "message_template": message_template,
                        "send_start_time": send_start_time,
                        "timezone": (get_active_account() or {}).get("timezone") or "Asia/Kolkata",
                    })

                    if response and response.status_code == 200:
                        st.success("Campaign created successfully!")
                        st.rerun()
                    else:
                        detail = response.json().get("detail", "Failed to create campaign.") if response is not None else "Failed to create campaign."
                        st.error(detail)
                else:
                    st.error("Please fill in campaign name and message template.")

    with tab2:
        st.subheader("My Campaigns")

        response = api_request("GET", "/campaigns/overview")
        if response and response.status_code == 200:
            campaigns = response.json()["campaigns"]

            if campaigns:
                for campaign in campaigns:
                    title = f"📧 {campaign['name']} - {campaign['status'].title()}"
                    with st.expander(title):
                        st.write(f"**Description:** {campaign.get('description') or 'No notes'}")
                        st.write(f"**Sender:** {campaign['sender_email']}")
                        st.write(f"**Scheduled Start:** {campaign.get('send_start_time') or 'Not scheduled'}")

                        stats = campaign["stats"]
                        col1, col2, col3, col4, col5 = st.columns(5)
                        col1.metric("Leads", stats["total_leads"])
                        col2.metric("Pending", stats["pending"])
                        col3.metric("Sent", stats["sent"])
                        col4.metric("Opened", stats["opened"])
                        col5.metric("Replies", stats["replied"])

                        action1, action2, action3, action4 = st.columns(4)

                        if action1.button("🚀 Send Now", key=f"send_now_{campaign['id']}"):
                            send_response = api_request("POST", f"/campaigns/{campaign['id']}/send-now")
                            if send_response and send_response.status_code == 200:
                                st.success("Campaign started instantly.")
                                st.rerun()
                            else:
                                detail = send_response.json().get("detail", "Failed to send now.") if send_response is not None else "Failed to send now."
                                st.error(detail)

                        if action2.button("⏰ Run Scheduled / Resume", key=f"schedule_{campaign['id']}"):
                            send_response = api_request("POST", f"/campaigns/{campaign['id']}/send")
                            if send_response and send_response.status_code == 200:
                                st.success(send_response.json()["message"])
                                st.rerun()
                            else:
                                detail = send_response.json().get("detail", "Failed to start campaign.") if send_response is not None else "Failed to start campaign."
                                st.error(detail)

                        if action3.button("📊 View Lead Details", key=f"details_{campaign['id']}"):
                            st.session_state.selected_campaign = campaign["id"]

                        if action4.button("🗑️ Delete", key=f"delete_{campaign['id']}"):
                            delete_response = api_request("DELETE", f"/campaigns/{campaign['id']}")
                            if delete_response and delete_response.status_code == 200:
                                st.success("Campaign deleted!")
                                st.rerun()
                            else:
                                st.error("Failed to delete campaign.")

                        if campaign.get("recent_activity"):
                            st.markdown("**Recent Activity**")
                            activity_df = pd.DataFrame(campaign["recent_activity"])
                            st.dataframe(activity_df, use_container_width=True)
            else:
                st.info("No campaigns yet. Create your first campaign!")
        else:
            st.error("Failed to load campaigns.")

    with tab3:
        st.subheader("Upload Leads")
        st.info(
            "Upload a CSV with email and name columns. Extra fields like company, title, phone, "
            "website, linkedin, source, notes, timezone, and priority will also be saved."
        )

        response = api_request("GET", "/campaigns/")
        if response and response.status_code == 200:
            campaigns = response.json()
            campaign_options = {c["name"]: c["id"] for c in campaigns}

            if campaign_options:
                selected_campaign = st.selectbox("Select Campaign", options=list(campaign_options.keys()))
                uploaded_file = st.file_uploader("Choose CSV file", type=["csv"])

                if uploaded_file is not None:
                    try:
                        df = pd.read_csv(uploaded_file)
                        st.write("Preview of uploaded data:")
                        st.dataframe(df.head(), use_container_width=True)

                        if st.button("Upload Leads"):
                            uploaded_file.seek(0)
                            files = {"file": ("leads.csv", uploaded_file, "text/csv")}
                            campaign_id = campaign_options[selected_campaign]
                            upload_response = api_request("POST", f"/campaigns/{campaign_id}/upload-leads", files=files)

                            if upload_response and upload_response.status_code == 200:
                                result = upload_response.json()
                                st.success(
                                    f"Successfully uploaded {result['leads_count']} leads. "
                                    f"Skipped {result.get('skipped_rows', 0)} rows."
                                )
                            else:
                                detail = upload_response.json().get("detail", "Upload failed.") if upload_response is not None else "Upload failed."
                                st.error(detail)
                    except Exception as e:
                        st.error(f"Error reading CSV: {str(e)}")
            else:
                st.info("Create a campaign first before uploading leads.")
        else:
            st.error("Failed to load campaigns.")

    with tab4:
        accounts_page(show_header=False)


def analytics_dashboard():
    st.markdown("# 📊 Analytics Dashboard")
    st.markdown("View campaign performance and jump into lead-level activity.")

    response = api_request("GET", "/analytics/dashboard")
    if response and response.status_code == 200:
        data = response.json()
        campaigns = data["campaigns"]

        if campaigns:
            total_campaigns = len(campaigns)
            total_leads = sum(c["stats"]["total_leads"] for c in campaigns)
            total_sent = sum(c["stats"]["sent"] for c in campaigns)
            total_read = sum(c["stats"]["read"] for c in campaigns)
            total_clicked = sum(c["stats"]["clicked"] for c in campaigns)

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Campaigns", total_campaigns)
            col2.metric("Leads", total_leads)
            col3.metric("Sent", total_sent)
            col4.metric("Opened", total_read)
            col5.metric("Clicked", total_clicked)

            st.markdown("---")
            for campaign in campaigns:
                with st.expander(f"📧 {campaign['campaign_name']} - {campaign['status'].title()}"):
                    stats = campaign["stats"]
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Sent", f"{stats['sent']}/{stats['total_leads']}")
                    c2.metric("Open Rate", f"{(stats['read'] / stats['sent'] * 100):.1f}%" if stats["sent"] else "0.0%")
                    c3.metric("Click Rate", f"{(stats['clicked'] / stats['sent'] * 100):.1f}%" if stats["sent"] else "0.0%")

                    if st.button(f"View Lead Intelligence for {campaign['campaign_name']}", key=f"analytics_details_{campaign['campaign_id']}"):
                        st.session_state.selected_campaign = campaign["campaign_id"]
        else:
            st.info("No campaigns found.")
    else:
        st.error("Failed to load dashboard data.")


def lead_intelligence_page():
    st.markdown("# 🧠 Lead Intelligence")
    st.markdown("Get detailed info on every lead, including company data, next send timing, and email history.")

    campaigns_response = api_request("GET", "/campaigns/")
    if not campaigns_response or campaigns_response.status_code != 200:
        st.error("Failed to load campaigns.")
        return

    campaigns = campaigns_response.json()
    if not campaigns:
        st.info("No campaigns found. Create a campaign first.")
        return

    campaign_names = [campaign["name"] for campaign in campaigns]
    selected_index = 0
    if st.session_state.selected_campaign:
        for idx, campaign in enumerate(campaigns):
            if campaign["id"] == st.session_state.selected_campaign:
                selected_index = idx
                break

    selected_name = st.selectbox("Select Campaign", options=campaign_names, index=selected_index)
    selected_campaign = next(c for c in campaigns if c["name"] == selected_name)
    st.session_state.selected_campaign = selected_campaign["id"]

    leads_response = api_request("GET", f"/analytics/campaign/{selected_campaign['id']}/leads")
    if not leads_response or leads_response.status_code != 200:
        st.error("Failed to load lead details.")
        return

    leads = leads_response.json()
    if not leads:
        st.info("No leads found for this campaign.")
        return

    df = pd.DataFrame(leads)

    search_term = st.text_input("Search leads by name, email, company, title")
    statuses = sorted(df["status"].dropna().unique().tolist())
    selected_statuses = st.multiselect("Filter by status", statuses, default=statuses)

    filtered_df = df[df["status"].isin(selected_statuses)].copy()
    if search_term:
        mask = filtered_df.fillna("").astype(str).apply(
            lambda row: row.str.contains(search_term, case=False).any(),
            axis=1
        )
        filtered_df = filtered_df[mask]

    columns_to_show = [
        "name", "email", "company", "title", "status", "send_status",
        "priority", "reply_category", "next_send_at", "last_event_at"
    ]
    st.dataframe(filtered_df[columns_to_show], use_container_width=True)

    labels = [f"{row['name']} - {row['email']}" for _, row in filtered_df.iterrows()]
    if not labels:
        st.info("No leads match your filters.")
        return

    selected_label = st.selectbox("Lead Detail", labels)
    selected_row = filtered_df.iloc[labels.index(selected_label)]

    st.markdown("## Lead Detail")
    left, right = st.columns(2)

    with left:
        st.write(f"**Name:** {selected_row['name']}")
        st.write(f"**Email:** {selected_row['email']}")
        st.write(f"**Company:** {selected_row.get('company') or 'N/A'}")
        st.write(f"**Title:** {selected_row.get('title') or 'N/A'}")
        st.write(f"**Phone:** {selected_row.get('phone') or 'N/A'}")
        st.write(f"**Website:** {selected_row.get('website') or 'N/A'}")
        st.write(f"**LinkedIn:** {selected_row.get('linkedin_url') or 'N/A'}")
        st.write(f"**Location:** {selected_row.get('location') or 'N/A'}")
        st.write(f"**Source:** {selected_row.get('source') or 'N/A'}")
        st.write(f"**Priority:** {selected_row.get('priority') or 'normal'}")
        st.write(f"**Reply Category:** {selected_row.get('reply_category') or 'N/A'}")
        st.write(f"**Next Send:** {selected_row.get('next_send_at') or 'Not scheduled'}")
        st.write(f"**Notes:** {selected_row.get('notes') or 'None'}")

        custom_fields = selected_row.get("custom_fields")
        if isinstance(custom_fields, dict) and custom_fields:
            st.markdown("### Custom Fields")
            st.json(custom_fields)

    with right:
        st.markdown("### Activity Timeline")
        history = selected_row.get("email_history") or []
        if history:
            history_df = pd.DataFrame(history)
            st.dataframe(history_df, use_container_width=True)
        else:
            st.info("No email history for this lead yet.")


def inbox_page():
    st.markdown("# 📥 Unified Inbox")
    st.markdown("View messages from the currently selected Gmail account.")

    response = api_request("GET", "/inbox/")
    if response and response.status_code == 200:
        data = response.json()
        messages = data.get("messages", [])

        if not messages:
            st.info("No recent inbox messages were found.")
            return

        for message in messages:
            message_id = message.get("id")
            snippet = message.get("snippet", "")
            st.markdown(f"**Message ID:** {message_id}")
            st.write(snippet)
            st.markdown("---")
    else:
        st.error("Failed to load inbox messages.")


def accounts_page(show_header=True):
    if show_header:
        st.markdown("# 👤 Account Manager")
        st.markdown("Connect multiple Gmail accounts, switch between them, and logout specific accounts.")

    add_response = api_request("GET", "/auth/login")
    if add_response and add_response.status_code == 200:
        st.link_button("➕ Connect Another Google Account", add_response.json()["authorization_url"])

    if not st.session_state.accounts:
        st.info("No accounts connected.")
        return

    for account in st.session_state.accounts:
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.write(f"**{account['email']}**")
            st.caption(f"Timezone: {account['timezone']} | Daily limit: {account['daily_limit']}")
        with col2:
            if st.button("Make Active", key=f"active_{account['id']}"):
                st.session_state.active_account_id = account["id"]
                persist_accounts_to_query_params()
                st.rerun()
        with col3:
            if st.button("Logout", key=f"logout_{account['id']}"):
                api_request("POST", "/auth/logout", token=account["token"])
                st.session_state.accounts = [a for a in st.session_state.accounts if a["id"] != account["id"]]
                if st.session_state.active_account_id == account["id"]:
                    st.session_state.active_account_id = st.session_state.accounts[0]["id"] if st.session_state.accounts else None
                persist_accounts_to_query_params()
                st.rerun()


def main():
    st.set_page_config(
        page_title="Email Automation",
        page_icon="📧",
        layout="wide"
    )

    init_state()
    restore_accounts_from_query_params()
    handle_auth_callback()

    with st.sidebar:
        st.title("Navigation")

        if st.session_state.accounts:
            active = get_active_account()
            if active:
                st.write(f"👤 {active['email']}")
            render_account_switcher()
            page = st.radio(
                "Go to",
                ["Campaign Manager", "Analytics Dashboard", "Lead Intelligence", "Inbox", "Accounts", "Logout"],
                label_visibility="collapsed"
            )
        else:
            st.write("Please login to continue")
            page = "Login"

    if not st.session_state.accounts:
        login_page()
        return

    if page == "Campaign Manager":
        campaign_manager()
    elif page == "Analytics Dashboard":
        analytics_dashboard()
    elif page == "Lead Intelligence":
        lead_intelligence_page()
    elif page == "Inbox":
        inbox_page()
    elif page == "Accounts":
        accounts_page()
    elif page == "Logout":
        st.session_state.accounts = []
        st.session_state.active_account_id = None
        persist_accounts_to_query_params()
        st.rerun()


if __name__ == "__main__":
    main()
