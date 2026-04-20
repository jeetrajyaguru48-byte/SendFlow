import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Upload, Play, Pause, Trash2, Eye, MousePointerClick, AlertCircle, Clock, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/api/client";

const CampaignDetail = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { token } = useAuth();

  const [campaign, setCampaign] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [leads, setLeads] = useState<any[]>([]);
  const [loadingCampaign, setLoadingCampaign] = useState(true);
  const [loadingDetails, setLoadingDetails] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [togglingStatus, setTogglingStatus] = useState(false);

  useEffect(() => {
    if (!token || !id) return;

    const campaignId = parseInt(id, 10);

    const fetchData = async () => {
      setLoadingCampaign(true);
      setLoadingDetails(true);
      try {
        const [campaignResult, statsResult, leadsResult] = await Promise.allSettled([
          api.getCampaign(token, campaignId),
          api.getCampaignStats(token, campaignId),
          api.getCampaignLeads(token, campaignId),
        ]);

        if (campaignResult.status !== "fulfilled") {
          throw campaignResult.reason;
        }

        setCampaign(campaignResult.value);
        setError(null);

        if (statsResult.status === "fulfilled") {
          setStats(statsResult.value);
        } else {
          setStats(null);
        }

        if (leadsResult.status === "fulfilled") {
          setLeads(leadsResult.value || []);
        } else {
          setLeads([]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load campaign');
        setCampaign(null);
        setStats(null);
        setLeads([]);
      } finally {
        setLoadingCampaign(false);
        setLoadingDetails(false);
      }
    };

    fetchData();
  }, [token, id]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !token || !id) return;
    const campaignId = parseInt(id, 10);

    setUploading(true);
    try {
      await api.uploadLeads(token, campaignId, file);
      toast({
        title: 'Success',
        description: 'Leads uploaded successfully',
      });

      // Reload leads
      const updatedLeads = await api.getCampaignLeads(token, campaignId);
      setLeads(updatedLeads || []);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to upload leads';
      toast({
        title: 'Error',
        description: errorMsg,
        variant: 'destructive',
      });
    } finally {
      setUploading(false);
    }
  };

  const handleStartCampaign = async () => {
    if (!token || !id) return;
    const campaignId = parseInt(id, 10);

    setStarting(true);
    try {
      await api.startCampaign(token, campaignId);
      toast({
        title: 'Campaign started!',
        description: 'Emails will be sent with human-like delays.',
      });

      // Reload campaign
      const updated = await api.getCampaign(token, campaignId);
      setCampaign(updated);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to start campaign';
      toast({
        title: 'Error',
        description: errorMsg,
        variant: 'destructive',
      });
    } finally {
      setStarting(false);
    }
  };

  const handleSendNow = async () => {
    if (!token || !id) return;
    const campaignId = parseInt(id, 10);

    setStarting(true);
    try {
      await api.sendCampaignNow(token, campaignId);
      toast({
        title: 'Campaign started immediately!',
        description: 'Emails are being sent now regardless of time settings.',
      });

      // Reload campaign and leads
      const [updated, leadsData] = await Promise.all([
        api.getCampaign(token, campaignId),
        api.getCampaignLeads(token, campaignId),
      ]);
      setCampaign(updated);
      setLeads(leadsData || []);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to start campaign';
      toast({
        title: 'Error',
        description: errorMsg,
        variant: 'destructive',
      });
    } finally {
      setStarting(false);
    }
  };

  const handleDelete = async () => {
    if (!token || !id) return;
    if (!confirm('Are you sure? This cannot be undone.')) return;
    const campaignId = parseInt(id, 10);

    try {
      await api.deleteCampaign(token, campaignId);
      toast({
        title: 'Campaign deleted',
      });
      navigate('/');
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to delete campaign';
      toast({
        title: 'Error',
        description: errorMsg,
        variant: 'destructive',
      });
    }
  };

  const reloadCampaignData = async (campaignId: number) => {
    if (!token) return;
    const [updatedCampaign, updatedStats, updatedLeads] = await Promise.all([
      api.getCampaign(token, campaignId),
      api.getCampaignStats(token, campaignId),
      api.getCampaignLeads(token, campaignId),
    ]);
    setCampaign(updatedCampaign);
    setStats(updatedStats);
    setLeads(updatedLeads || []);
  };

  const handlePauseCampaign = async () => {
    if (!token || !id) return;
    const campaignId = parseInt(id, 10);
    setTogglingStatus(true);
    try {
      await api.pauseCampaign(token, campaignId);
      await reloadCampaignData(campaignId);
      toast({
        title: "Campaign paused",
        description: "No new emails will be scheduled until you resume it.",
      });
    } catch (err) {
      toast({
        title: "Error",
        description: err instanceof Error ? err.message : "Failed to pause campaign",
        variant: "destructive",
      });
    } finally {
      setTogglingStatus(false);
    }
  };

  const handleResumeCampaign = async () => {
    if (!token || !id) return;
    const campaignId = parseInt(id, 10);
    setTogglingStatus(true);
    try {
      await api.resumeCampaign(token, campaignId);
      await reloadCampaignData(campaignId);
      toast({
        title: "Campaign resumed",
        description: "The scheduler will pick it up again on the next run.",
      });
    } catch (err) {
      toast({
        title: "Error",
        description: err instanceof Error ? err.message : "Failed to resume campaign",
        variant: "destructive",
      });
    } finally {
      setTogglingStatus(false);
    }
  };

  if (loadingCampaign) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-muted-foreground">Loading campaign...</p>
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="space-y-4">
        <Link to="/app">
          <Button variant="ghost">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to campaigns
          </Button>
        </Link>
        <Card className="bg-red-500/10 border-red-500/30">
          <CardContent className="py-12 text-center">
            <AlertCircle className="h-8 w-8 text-red-600 mx-auto mb-3" />
            <p className="text-red-700 font-semibold mb-2">Campaign not found</p>
            <p className="text-red-600 text-sm">{error || 'The campaign you are looking for does not exist or you do not have access to it.'}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const openRate = stats?.sent ? ((stats.read / stats.sent) * 100).toFixed(1) : 0;
  const clickRate = stats?.sent ? ((stats.clicked / stats.sent) * 100).toFixed(1) : 0;
  const nextCampaignSendAt = campaign.next_send_at || campaign.send_start_time || null;
  const pendingLeadCount = leads.filter((lead: any) => lead.status === "pending" && !lead.opted_out).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/app">
            <Button variant="ghost" size="icon" className="text-muted-foreground">
              <ArrowLeft className="h-5 w-5" />
            </Button>
          </Link>
          <div>
            <h1 className="text-3xl font-bold text-foreground">{campaign.name}</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Status: <span className="font-semibold capitalize">{campaign.status}</span>
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleDelete}
          className="text-red-600 border-red-600/30 hover:bg-red-600/10"
        >
          <Trash2 className="h-4 w-4 mr-2" />
          Delete
        </Button>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="bg-card border-border">
          <CardContent className="pt-6">
            <p className="text-2xl font-bold text-foreground">{stats?.total_leads || 0}</p>
            <p className="text-xs text-muted-foreground mt-1">Total Leads</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-6">
            <p className="text-2xl font-bold text-foreground">{stats?.sent || 0}</p>
            <p className="text-xs text-muted-foreground mt-1">Sent</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2">
              <p className="text-2xl font-bold text-foreground">{openRate}%</p>
              <Eye className="h-4 w-4 text-muted-foreground" />
            </div>
            <p className="text-xs text-muted-foreground mt-1">Open Rate</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2">
              <p className="text-2xl font-bold text-foreground">{clickRate}%</p>
              <MousePointerClick className="h-4 w-4 text-muted-foreground" />
            </div>
            <p className="text-xs text-muted-foreground mt-1">Click Rate</p>
          </CardContent>
        </Card>
      </div>

      {loadingDetails && (
        <Card className="bg-card border-border">
          <CardContent className="py-4">
            <p className="text-sm text-muted-foreground">Loading campaign activity and lead details...</p>
          </CardContent>
        </Card>
      )}

      {/* Next Send Summary */}
      {(campaign.status === 'running' || campaign.status === 'scheduled' || campaign.status === 'paused') && (
        <Card className="bg-gradient-to-r from-blue-500/10 to-purple-500/10 border border-blue-500/30">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Clock className="h-5 w-5 text-blue-500" />
              Next Email
            </CardTitle>
            <CardDescription>
              Campaign-level schedule and delivery state
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-blue-700/70">Next send time</p>
                <p className="mt-2 text-sm font-semibold text-blue-900">
                  {nextCampaignSendAt ? new Date(nextCampaignSendAt).toLocaleString() : "Waiting for next scheduler slot"}
                </p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Campaign status</p>
                <p className="mt-2 text-sm font-semibold text-foreground capitalize">{campaign.status}</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Pending leads</p>
                <p className="mt-2 text-sm font-semibold text-foreground">{pendingLeadCount}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Message Preview */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-base">Message Template</CardTitle>
          <CardDescription>
            Subject: {campaign.subject_template || "No custom subject saved"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {campaign.description && (
            <div className="mb-4 rounded-lg border border-border p-4 text-sm text-muted-foreground">
              {campaign.description}
            </div>
          )}
          <div className="bg-muted rounded p-4 text-sm text-foreground whitespace-pre-wrap">
            {campaign.message_template}
          </div>
        </CardContent>
      </Card>

      {campaign.send_schedule && campaign.send_schedule.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-base">Send Schedule</CardTitle>
            <CardDescription>
              This campaign will send the configured number of emails during the selected hours.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-3">
              {campaign.send_schedule.map((entry: any, index: number) => (
                <div key={index} className="rounded-lg border border-border p-4">
                  <p className="text-sm text-muted-foreground">Hour</p>
                  <p className="text-lg font-semibold text-foreground">{String(entry.hour).padStart(2, '0')}:00</p>
                  <p className="text-sm text-muted-foreground mt-1">{entry.count} emails</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Upload Leads */}
      {campaign.status === 'draft' && (
        <Card className="bg-card border-border border-blue-500/30 bg-blue-500/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Upload className="h-4 w-4" />
              Upload Leads
            </CardTitle>
            <CardDescription>Add your email list (CSV format)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="border-2 border-dashed border-muted-foreground/30 rounded-lg p-8 text-center hover:border-primary/50 transition">
                <input
                  type="file"
                  accept=".csv"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  className="hidden"
                  id="csv-upload"
                />
                <label htmlFor="csv-upload" className="cursor-pointer block">
                  <p className="text-sm font-medium text-foreground mb-1">Drop CSV here or click to browse</p>
                  <p className="text-xs text-muted-foreground">Columns: Email, Name</p>
                </label>
              </div>
              <p className="text-xs text-muted-foreground">
                💡 CSV should have Email and Name columns. Supports: email, personal_email, contact_email, etc.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Leads Table with Full Analytics */}
      {leads.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-base">Lead Analytics ({leads.length})</CardTitle>
            <CardDescription>Detailed tracking for every lead being sent emails</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left py-3 px-3 font-semibold text-muted-foreground">Email</th>
                    <th className="text-left py-3 px-3 font-semibold text-muted-foreground">Name</th>
                    <th className="text-left py-3 px-3 font-semibold text-muted-foreground">Company</th>
                    <th className="text-left py-3 px-3 font-semibold text-muted-foreground">Title</th>
                    <th className="text-center py-3 px-3 font-semibold text-muted-foreground">Status</th>
                    <th className="text-center py-3 px-3 font-semibold text-muted-foreground">
                      <div className="flex items-center justify-center gap-1">
                        <span>Sent</span>
                      </div>
                    </th>
                    <th className="text-center py-3 px-3 font-semibold text-muted-foreground">
                      <div className="flex items-center justify-center gap-1">
                        <Eye className="h-3 w-3" />
                        <span>Opened</span>
                      </div>
                    </th>
                    <th className="text-center py-3 px-3 font-semibold text-muted-foreground">
                      <div className="flex items-center justify-center gap-1">
                        <MousePointerClick className="h-3 w-3" />
                        <span>Clicked</span>
                      </div>
                    </th>
                    <th className="text-center py-3 px-3 font-semibold text-muted-foreground">Reply</th>
                    <th className="text-center py-3 px-3 font-semibold text-muted-foreground">Bounce</th>
                    <th className="text-left py-3 px-3 font-semibold text-muted-foreground">Next Send</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead: any) => (
                    <tr key={lead.email} className="border-b border-border hover:bg-muted/30 transition">
                      <td className="py-3 px-3 text-foreground font-medium">{lead.email}</td>
                      <td className="py-3 px-3 text-foreground">{lead.name}</td>
                      <td className="py-3 px-3 text-foreground">{lead.company || "—"}</td>
                      <td className="py-3 px-3 text-foreground">{lead.title || "—"}</td>
                      <td className="py-3 px-3 text-center">
                        <span className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                          lead.status === 'sent' ? 'bg-green-500/20 text-green-700' :
                          lead.status === 'pending' ? 'bg-yellow-500/20 text-yellow-700' :
                          lead.status === 'bounced' ? 'bg-red-500/20 text-red-700' :
                          lead.status === 'replied' ? 'bg-blue-500/20 text-blue-700' :
                          lead.status === 'read' ? 'bg-purple-500/20 text-purple-700' :
                          lead.status === 'clicked' ? 'bg-indigo-500/20 text-indigo-700' :
                          'bg-gray-500/20 text-gray-700'
                        }`}>
                          {lead.status}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center text-sm">
                        {lead.sent_at ? (
                          <div className="text-green-600 font-semibold">✓</div>
                        ) : (
                          <div className="text-muted-foreground">—</div>
                        )}
                      </td>
                      <td className="py-3 px-3 text-center text-sm">
                        {lead.read_at ? (
                          <div className="flex items-center justify-center">
                            <Eye className="h-4 w-4 text-purple-600" />
                          </div>
                        ) : (
                          <div className="text-muted-foreground">—</div>
                        )}
                      </td>
                      <td className="py-3 px-3 text-center text-sm">
                        {lead.clicked_at ? (
                          <div className="flex items-center justify-center">
                            <MousePointerClick className="h-4 w-4 text-blue-600" />
                          </div>
                        ) : (
                          <div className="text-muted-foreground">—</div>
                        )}
                      </td>
                      <td className="py-3 px-3 text-center text-sm">
                        {lead.replied_at ? (
                          <div className="font-semibold text-green-600">✓</div>
                        ) : (
                          <div className="text-muted-foreground">—</div>
                        )}
                      </td>
                      <td className="py-3 px-3 text-center text-sm">
                        {lead.bounced_at ? (
                          <div className="font-semibold text-red-600">✗</div>
                        ) : (
                          <div className="text-muted-foreground">—</div>
                        )}
                      </td>
                      <td className="py-3 px-3 text-sm">
                        {lead.next_send_at ? (
                          <div>
                            <div className="text-foreground font-medium text-xs">
                              {new Date(lead.next_send_at).toLocaleString()}
                            </div>
                            <div className={`text-xs mt-1 ${
                              lead.send_status === 'Sending soon' ? 'text-green-600 font-semibold' :
                              lead.send_status === 'Scheduled' ? 'text-blue-600' :
                              lead.send_status === 'Campaign not running' ? 'text-gray-600' :
                              lead.send_status === 'Lead opted out' ? 'text-red-600' :
                              'text-yellow-600'
                            }`}>
                              {lead.send_status}
                            </div>
                          </div>
                        ) : (
                          <span className="text-muted-foreground text-xs">{lead.send_status}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Action Buttons */}
      <div className="flex gap-3 flex-wrap">
        {campaign.status === 'draft' && leads.length > 0 && (
          <>
            <Button
              onClick={handleStartCampaign}
              disabled={starting}
              className="gradient-accent text-white border-0 hover:opacity-90"
            >
              <Clock className="h-4 w-4 mr-2" />
              {starting ? 'Starting...' : 'Start Campaign'}
            </Button>
            <Button
              onClick={handleSendNow}
              disabled={starting}
              className="bg-orange-600 text-white border-0 hover:bg-orange-700"
            >
              <Zap className="h-4 w-4 mr-2" />
              {starting ? 'Sending...' : 'Send Now'}
            </Button>
          </>
        )}
        {campaign.status === 'running' && (
          <>
            <Button
              onClick={handlePauseCampaign}
              disabled={togglingStatus}
              className="bg-amber-600 text-white border-0 hover:bg-amber-700"
            >
              <Pause className="h-4 w-4 mr-2" />
              {togglingStatus ? 'Pausing...' : 'Pause Campaign'}
            </Button>
            <Button
              onClick={handleSendNow}
              disabled={starting}
              className="bg-orange-600 text-white border-0 hover:bg-orange-700"
              title="Speed up delivery - send more emails immediately"
            >
              <Zap className="h-4 w-4 mr-2" />
              {starting ? 'Sending...' : 'Send More Now'}
            </Button>
          </>
        )}
        {(campaign.status === 'paused' || campaign.status === 'scheduled') && leads.length > 0 && (
          <Button
            onClick={handleResumeCampaign}
            disabled={togglingStatus}
            className="gradient-accent text-white border-0 hover:opacity-90"
          >
            <Play className="h-4 w-4 mr-2" />
            {togglingStatus ? 'Resuming...' : 'Resume Campaign'}
          </Button>
        )}
        {campaign.status === 'draft' && leads.length === 0 && (
          <Button disabled className="opacity-50">
            <AlertCircle className="h-4 w-4 mr-2" />
            Upload leads first
          </Button>
        )}
      </div>
    </div>
  );
};

export default CampaignDetail;
