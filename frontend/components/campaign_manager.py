import streamlit as st
import pandas as pd
import requests

def campaign_manager_component(api_base_url="http://localhost:8000"):
    """Campaign management interface."""
    st.title("📈 Campaign Manager")

    tab1, tab2, tab3 = st.tabs(["Create Campaign", "My Campaigns", "Upload Leads"])

    with tab1:
        create_campaign_tab(api_base_url)

    with tab2:
        my_campaigns_tab(api_base_url)

    with tab3:
        upload_leads_tab(api_base_url)

def create_campaign_tab(api_base_url):
    """Create new campaign tab."""
    st.subheader("Create New Campaign")
    st.info("All campaigns send on a fixed schedule: 30 emails per day, evenly spaced, between 3:00 PM and 9:00 PM IST.")

    with st.form("campaign_form"):
        campaign_name = st.text_input("Campaign Name")
        message_template = st.text_area(
            "Message Template",
            height=200,
            help="Use {name} to personalize messages. Example: 'Hi {name}, how are you?'"
        )

        submitted = st.form_submit_button("Create Campaign")
        if submitted:
            if campaign_name and message_template:
                headers = {'Authorization': f'Bearer {st.session_state.token}'}
                response = requests.post(
                    f"{api_base_url}/campaigns/",
                    json={
                        "name": campaign_name,
                        "message_template": message_template
                    },
                    headers=headers
                )

                if response.status_code == 200:
                    st.success("Campaign created successfully!")
                    st.rerun()
                else:
                    st.error("Failed to create campaign.")
            else:
                st.error("Please fill in all fields.")

def my_campaigns_tab(api_base_url):
    """My campaigns tab."""
    st.subheader("My Campaigns")

    headers = {'Authorization': f'Bearer {st.session_state.token}'}
    response = requests.get(f"{api_base_url}/campaigns/", headers=headers)

    if response.status_code == 200:
        campaigns = response.json()

        if campaigns:
            for campaign in campaigns:
                with st.expander(f"📧 {campaign['name']} - {campaign['status'].title()}"):
                    st.write(f"**Created:** {campaign['created_at']}")
                    st.write(f"**Status:** {campaign['status']}")

                    # Get campaign stats
                    stats_response = requests.get(
                        f"{api_base_url}/analytics/campaign/{campaign['id']}/stats",
                        headers=headers
                    )
                    if stats_response.status_code == 200:
                        stats = stats_response.json()
                        col1, col2, col3, col4, col5, col6 = st.columns(6)
                        col1.metric("Total", stats['total_leads'])
                        col2.metric("Sent", stats['sent'])
                        col3.metric("Read", stats['read'])
                        col4.metric("Clicked", stats['clicked'])
                        col5.metric("Bounced", stats['bounced'])
                        col6.metric("Replied", stats['replied'])

                    # Action buttons
                    col1, col2, col3 = st.columns(3)
                    if campaign['status'] in ['draft', 'completed', 'failed']:
                        if col1.button("🚀 Start Campaign", key=f"start_{campaign['id']}"):
                            send_response = requests.post(
                                f"{api_base_url}/campaigns/{campaign['id']}/send",
                                headers=headers
                            )
                            if send_response.status_code == 200:
                                st.success("Campaign started! Emails will be sent in the background.")
                                st.rerun()
                            else:
                                st.error("Failed to start campaign.")

                    if col2.button("📊 View Details", key=f"details_{campaign['id']}"):
                        st.session_state.selected_campaign = campaign['id']

                    if col3.button("🗑️ Delete", key=f"delete_{campaign['id']}"):
                        delete_response = requests.delete(
                            f"{api_base_url}/campaigns/{campaign['id']}",
                            headers=headers
                        )
                        if delete_response.status_code == 200:
                            st.success("Campaign deleted!")
                            st.rerun()
                        else:
                            st.error("Failed to delete campaign.")
        else:
            st.info("No campaigns yet. Create your first campaign!")
    else:
        st.error("Failed to load campaigns.")

def upload_leads_tab(api_base_url):
    """Upload leads tab."""
    st.subheader("Upload Leads")

    headers = {'Authorization': f'Bearer {st.session_state.token}'}
    response = requests.get(f"{api_base_url}/campaigns/", headers=headers)

    if response.status_code == 200:
        campaigns = response.json()
        campaign_options = {c['name']: c['id'] for c in campaigns if c['status'] == 'draft'}

        if campaign_options:
            selected_campaign = st.selectbox(
                "Select Campaign",
                options=list(campaign_options.keys())
            )

            uploaded_file = st.file_uploader("Choose CSV file", type=['csv'])

            if uploaded_file is not None:
                try:
                    df = pd.read_csv(uploaded_file)
                    st.write("Preview of uploaded data:")
                    st.dataframe(df.head())

                    if st.button("Upload Leads"):
                        # Reset file pointer
                        uploaded_file.seek(0)

                        files = {'file': ('leads.csv', uploaded_file, 'text/csv')}
                        campaign_id = campaign_options[selected_campaign]

                        response = requests.post(
                            f"{api_base_url}/campaigns/{campaign_id}/upload-leads",
                            files=files,
                            headers=headers
                        )

                        if response.status_code == 200:
                            result = response.json()
                            st.success(f"Successfully uploaded {result['leads_count']} leads!")
                        else:
                            st.error("Failed to upload leads.")

                except Exception as e:
                    st.error(f"Error reading CSV: {str(e)}")
        else:
            st.info("Create a campaign first before uploading leads.")
    else:
        st.error("Failed to load campaigns.")
