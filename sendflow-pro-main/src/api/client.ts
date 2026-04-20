// API client for FastAPI backend
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  'http://localhost:8000';

const extractErrorMessage = (error: unknown, fallback: string) => {
  if (!error || typeof error !== "object") return fallback;

  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return "";
        const loc = Array.isArray((item as { loc?: unknown }).loc)
          ? (item as { loc?: Array<string | number> }).loc?.join(".")
          : "";
        const msg = typeof (item as { msg?: unknown }).msg === "string"
          ? (item as { msg?: string }).msg
          : JSON.stringify(item);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean);

    if (parts.length > 0) return parts.join(" | ");
  }

  return fallback;
};

export const api = {
  // Auth
  getLoginUrl: async (loginHint?: string) => {
    const query = loginHint ? `?login_hint=${encodeURIComponent(loginHint)}` : "";
    const res = await fetch(`${API_BASE}/auth/login${query}`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(extractErrorMessage(error, 'Failed to get login URL'));
    }
    return res.json();
  },

  getCurrentUser: async (token: string) => {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error('Unauthorized');
    return res.json();
  },

  updateAccountSettings: async (token: string, data: { daily_limit?: number; timezone?: string }) => {
    const res = await fetch(`${API_BASE}/auth/settings`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to update account settings"));
    }
    return res.json();
  },

  sendTestEmail: async (token: string) => {
    const res = await fetch(`${API_BASE}/auth/test-send`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to send test email"));
    }
    return res.json();
  },

  // Campaigns
  createCampaign: async (token: string, data: { 
    name: string; 
    description?: string;
    subject_template?: string;
    message_template: string; 
    is_sequence?: boolean;
    sequence_id?: number | null;
    ab_test_config?: any;
    send_schedule?: Array<{ hour: number; count: number }>;
    send_start_time?: string;
    timezone?: string;
    hourly_send_rate?: number;
    min_delay_minutes?: number;
    max_delay_minutes?: number;
    send_window_start?: string;
    send_window_end?: string;
    send_window_weekdays_only?: boolean;
  }) => {
    try {
      const res = await fetch(`${API_BASE}/campaigns/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(data),
      });
      if (res.status === 401) throw new Error('Unauthorized - please log in again');
      if (!res.ok) {
        const error = await res.json().catch(() => null);
        throw new Error(extractErrorMessage(error, `Failed to create campaign (${res.status})`));
      }
      return res.json();
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        throw new Error('Network error - backend may be unavailable');
      }
      throw err;
    }
  },

  getCampaigns: async (token: string) => {
    const res = await fetch(`${API_BASE}/campaigns/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error('Unauthorized - please log in again');
    if (!res.ok) throw new Error('Failed to fetch campaigns');
    return res.json();
  },

  getCampaign: async (token: string, id: number) => {
    const res = await fetch(`${API_BASE}/campaigns/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error('Unauthorized - please log in again');
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Failed to fetch campaign' }));
      throw new Error(extractErrorMessage(error, `Failed to fetch campaign (${res.status})`));
    }
    return res.json();
  },

  // Sequences
  createSequence: async (token: string, data: { name: string; description?: string }) => {
    const res = await fetch(`${API_BASE}/sequences/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, 'Failed to create sequence'));
    }
    return res.json();
  },

  getSequences: async (token: string) => {
    const res = await fetch(`${API_BASE}/sequences/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error('Failed to fetch sequences');
    return res.json();
  },

  createSequenceStep: async (token: string, sequenceId: number, data: {
    step_number: number;
    subject: string;
    body: string;
    delay_hours: number;
    sender_name?: string;
    priority: string;
    send_window_start?: string;
    send_window_end?: string;
    weekdays_only: boolean;
  }) => {
    const res = await fetch(`${API_BASE}/sequences/${sequenceId}/steps`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        ...data,
        sequence_id: sequenceId,
      }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, 'Failed to create sequence step'));
    }
    return res.json();
  },

  uploadLeads: async (token: string, campaignId: number, file: File) => {
    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(`${API_BASE}/campaigns/${campaignId}/upload-leads`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (res.status === 401) throw new Error('Unauthorized - please log in again');
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to upload leads' }));
        throw new Error(extractErrorMessage(error, `Failed to upload leads (${res.status})`));
      }
      return res.json();
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        throw new Error('Network error - backend may be unavailable');
      }
      throw err;
    }
  },

  previewLeadImport: async (token: string, campaignId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/import-preview`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to preview import"));
    }
    return res.json();
  },

  importLeadsWithMapping: async (
    token: string,
    campaignId: number,
    data: { campaign_id: number; rows: Record<string, string>[]; mapping: Record<string, string | null> }
  ) => {
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/import-with-mapping`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to import leads"));
    }
    return res.json();
  },

  createManualLead: async (
    token: string,
    campaignId: number,
    data: {
      email: string;
      name: string;
      company?: string;
      title?: string;
      phone?: string;
      website?: string;
      linkedin_url?: string;
      location?: string;
      source?: string;
      notes?: string;
      timezone?: string;
      priority?: string;
    }
  ) => {
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/leads`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to add lead"));
    }
    return res.json();
  },

  assignLeadsToCampaign: async (
    token: string,
    campaignId: number,
    data: { lead_ids: number[]; target_campaign_id: number }
  ) => {
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/leads/assign`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to assign leads"));
    }
    return res.json();
  },

  deleteLeads: async (token: string, campaignId: number, lead_ids: number[]) => {
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/leads`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ lead_ids }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to delete leads"));
    }
    return res.json();
  },

  updateLeadStage: async (
    token: string,
    campaignId: number,
    leadId: number,
    lifecycle_stage: string
  ) => {
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/leads/${leadId}/stage`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ lifecycle_stage }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to update lead stage"));
    }
    return res.json();
  },

  startCampaign: async (token: string, campaignId: number) => {
    try {
      const res = await fetch(`${API_BASE}/campaigns/${campaignId}/send`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) throw new Error('Unauthorized - please log in again');
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to start campaign' }));
        throw new Error(extractErrorMessage(error, `Failed to start campaign (${res.status})`));
      }
      return res.json();
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        throw new Error('Network error - backend may be unavailable');
      }
      throw err;
    }
  },

  sendCampaignNow: async (token: string, campaignId: number) => {
    try {
      const res = await fetch(`${API_BASE}/campaigns/${campaignId}/send-now`, {
        method: 'POST',
        headers: { 
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      if (res.status === 401) throw new Error('Unauthorized - please log in again');
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to start campaign' }));
        throw new Error(extractErrorMessage(error, `Failed to start campaign (${res.status})`));
      }
      return res.json();
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        throw new Error('Network error - backend may be unavailable. Check that http://localhost:8000 is running.');
      }
      throw err;
    }
  },

  pauseCampaign: async (token: string, campaignId: number) => {
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/pause`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error("Unauthorized - please log in again");
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to pause campaign"));
    }
    return res.json();
  },

  resumeCampaign: async (token: string, campaignId: number) => {
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/resume`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error("Unauthorized - please log in again");
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to resume campaign"));
    }
    return res.json();
  },

  deleteCampaign: async (token: string, campaignId: number) => {
    try {
      const res = await fetch(`${API_BASE}/campaigns/${campaignId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) throw new Error('Unauthorized - please log in again');
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to delete campaign' }));
        throw new Error(extractErrorMessage(error, `Failed to delete campaign (${res.status})`));
      }
      return res.json();
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        throw new Error('Network error - backend may be unavailable');
      }
      throw err;
    }
  },

  // Analytics
  getDashboard: async (token: string) => {
    const res = await fetch(`${API_BASE}/analytics/dashboard`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error('Failed to fetch dashboard');
    return res.json();
  },

  getCampaignStats: async (token: string, campaignId: number) => {
    const res = await fetch(`${API_BASE}/analytics/campaign/${campaignId}/stats`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error('Unauthorized - please log in again');
    if (!res.ok) throw new Error('Failed to fetch stats');
    return res.json();
  },

  getCampaignLeads: async (token: string, campaignId: number) => {
    const res = await fetch(`${API_BASE}/analytics/campaign/${campaignId}/leads`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error('Unauthorized - please log in again');
    if (!res.ok) throw new Error('Failed to fetch leads');
    return res.json();
  },

  getInbox: async (token: string) => {
    const res = await fetch(`${API_BASE}/inbox/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) throw new Error('Unauthorized - please log in again');
    if (!res.ok) throw new Error('Failed to fetch inbox');
    return res.json();
  },

  replyToInboxThread: async (token: string, data: { thread_id: string; to_email: string; subject: string; body: string }) => {
    const res = await fetch(`${API_BASE}/inbox/reply`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to send reply"));
    }
    return res.json();
  },

  markLeadNeedsFollowUp: async (token: string, leadId: number) => {
    const res = await fetch(`${API_BASE}/inbox/${leadId}/mark-follow-up`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to update lead"));
    }
    return res.json();
  },

  markLeadConverted: async (token: string, leadId: number) => {
    const res = await fetch(`${API_BASE}/inbox/${leadId}/mark-converted`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(extractErrorMessage(error, "Failed to update lead"));
    }
    return res.json();
  },

  getAnalyticsOverview: async (token: string) => {
    const res = await fetch(`${API_BASE}/analytics/overview`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error("Failed to fetch analytics overview");
    return res.json();
  },

  getAccountActivity: async (token: string) => {
    const res = await fetch(`${API_BASE}/analytics/account-activity`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error("Failed to fetch account activity");
    return res.json();
  },

  // Dev mode - test emails
  getTestEmails: async () => {
    const res = await fetch(`${API_BASE}/analytics/dev/test-emails`);
    if (!res.ok) throw new Error('Failed to fetch test emails');
    return res.json();
  },
};
