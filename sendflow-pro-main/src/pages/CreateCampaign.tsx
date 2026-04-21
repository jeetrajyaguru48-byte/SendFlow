import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronRight, FileUp, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/api/client";

type WizardStep = 1 | 2 | 3 | 4;

type SequenceStep = {
  step_number: number;
  subject: string;
  body: string;
  delay_hours: number;
};

const defaultMapping = {
  email: "",
  name: "",
  first_name: "",
  last_name: "",
  company: "",
  title: "",
  phone: "",
  website: "",
  linkedin_url: "",
  location: "",
  source: "",
  notes: "",
  timezone: "",
  priority: "",
};

const parseCsv = async (file: File): Promise<Record<string, string>[]> => {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (lines.length === 0) return [];
  const headers = lines[0].split(",").map((item) => item.trim());
  return lines.slice(1).map((line) => {
    const values = line.split(",").map((item) => item.trim());
    return headers.reduce<Record<string, string>>((acc, header, index) => {
      acc[header] = values[index] || "";
      return acc;
    }, {});
  });
};

const CreateCampaign = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const { token, user } = useAuth();
  const browserTimezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", []);

  const [step, setStep] = useState<WizardStep>(1);
  const [loading, setLoading] = useState(false);
  const [leadRows, setLeadRows] = useState<Record<string, string>[]>([]);
  const [leadHeaders, setLeadHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>(defaultMapping);

  const [formData, setFormData] = useState({
    name: "",
    description: "",
    subject_template: "",
    send_start_time: "",
  });

  const [sequenceSteps, setSequenceSteps] = useState<SequenceStep[]>([
    { step_number: 1, subject: "", body: "", delay_hours: 0 },
  ]);

  const completion = useMemo(() => (step / 4) * 100, [step]);
  const activePreview = sequenceSteps[Math.max(0, step === 3 ? sequenceSteps.length - 1 : 0)];

  const updateStepData = (index: number, patch: Partial<SequenceStep>) => {
    setSequenceSteps((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item))
    );
  };

  const addSequenceStep = () => {
    setSequenceSteps((current) => [
      ...current,
      {
        step_number: current.length + 1,
        subject: "",
        body: "",
        delay_hours: 72,
      },
    ]);
  };

  const removeSequenceStep = (index: number) => {
    setSequenceSteps((current) =>
      current
        .filter((_, itemIndex) => itemIndex !== index)
        .map((item, itemIndex) => ({ ...item, step_number: itemIndex + 1 }))
    );
  };

  const handleFile = async (file: File | null) => {
    if (!file) return;
    const rows = await parseCsv(file);
    setLeadRows(rows);
    setLeadHeaders(rows[0] ? Object.keys(rows[0]) : []);

    const suggestedMapping = { ...defaultMapping };
    Object.keys(suggestedMapping).forEach((field) => {
      const match = Object.keys(rows[0] || {}).find((header) => header.toLowerCase() === field || header.toLowerCase().includes(field.replace("_", "")));
      suggestedMapping[field as keyof typeof suggestedMapping] = match || "";
    });
    setMapping(suggestedMapping);
  };

  const canContinue = () => {
    if (step === 1) return Boolean(formData.name && formData.description);
    if (step === 2) return leadRows.length > 0 && Boolean(mapping.email);
    if (step === 3) return sequenceSteps.every((item) => item.subject && item.body);
    return true;
  };

  const handleSubmit = async () => {
    if (!token) return;

    setLoading(true);
    try {
      let sequenceId: number | null = null;
      if (sequenceSteps.length > 1) {
        const sequence = await api.createSequence(token, {
          name: `${formData.name} Sequence`,
          description: formData.description,
        });
        sequenceId = sequence.id;

        for (const sequenceStep of sequenceSteps) {
          await api.createSequenceStep(token, sequenceId, {
            ...sequenceStep,
            priority: "normal",
            weekdays_only: false,
            send_window_start: "15:00",
            send_window_end: "21:00",
          });
        }
      }

      const campaign = await api.createCampaign(token, {
        name: formData.name,
        description: formData.description,
        subject_template: formData.subject_template || sequenceSteps[0].subject,
        message_template: sequenceSteps[0].body,
        is_sequence: sequenceSteps.length > 1,
        sequence_id: sequenceId,
        send_start_time: formData.send_start_time ? new Date(formData.send_start_time).toISOString() : undefined,
        timezone: user?.timezone || browserTimezone,
      });

      if (leadRows.length > 0) {
        await api.importLeadsWithMapping(token, campaign.id, {
          campaign_id: campaign.id,
          rows: leadRows,
          mapping,
        });
      }

      toast({
        title: "Campaign ready",
        description: "Your campaign, lead import, and follow-up steps were saved.",
      });
      navigate(`/campaign/${campaign.id}`);
    } catch (err) {
      toast({
        title: "Campaign setup failed",
        description: err instanceof Error ? err.message : "Could not create campaign",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/app">
          <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-foreground">New Campaign Wizard</h1>
          <p className="text-sm text-muted-foreground">Campaign details, leads, sequence, then scheduling and launch.</p>
        </div>
      </div>

      <Card className="bg-card border-border">
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap gap-2 text-sm">
            {[
              "1. Campaign Details",
              "2. Select / Import Leads",
              "3. Compose Email Sequence",
              "4. Schedule & Launch",
            ].map((item, index) => (
              <div
                key={item}
                className={`rounded-full px-3 py-2 ${
                  step === index + 1 ? "bg-white/10 text-white" : "bg-muted/20 text-muted-foreground"
                }`}
              >
                {item}
              </div>
            ))}
          </div>
          <Progress value={completion} className="h-2" />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-6">
          {step === 1 && (
            <Card className="bg-card border-border">
              <CardHeader>
                <CardTitle>Step 1: Campaign Details</CardTitle>
                <CardDescription>Name the campaign and give the team some context.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Campaign Name</Label>
                  <Input value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label>Description</Label>
                  <Textarea rows={5} value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label>Primary Subject Line</Label>
                  <Input value={formData.subject_template} onChange={(e) => setFormData({ ...formData, subject_template: e.target.value })} placeholder="Quick note for {company}" />
                </div>
              </CardContent>
            </Card>
          )}

          {step === 2 && (
            <Card className="bg-card border-border">
              <CardHeader>
                <CardTitle>Step 2: Select / Import Leads</CardTitle>
                <CardDescription>Upload a CSV, map columns, and preview what will be imported.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="rounded-xl border-2 border-dashed border-border p-6">
                  <div className="flex items-center gap-3">
                    <FileUp className="h-5 w-5 text-muted-foreground" />
                    <input type="file" accept=".csv" onChange={(e) => handleFile(e.target.files?.[0] || null)} />
                  </div>
                </div>

                {leadHeaders.length > 0 && (
                  <div className="space-y-4">
                    <p className="font-medium text-foreground">Column Mapping</p>
                    <div className="grid gap-4 md:grid-cols-2">
                      {Object.keys(mapping).map((field) => (
                        <div key={field} className="space-y-2">
                          <Label className="capitalize">{field.replaceAll("_", " ")}</Label>
                          <select
                            value={mapping[field]}
                            onChange={(event) => setMapping((current) => ({ ...current, [field]: event.target.value }))}
                            className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
                          >
                            <option value="">Not mapped</option>
                            {leadHeaders.map((header) => (
                              <option key={header} value={header}>{header}</option>
                            ))}
                          </select>
                        </div>
                      ))}
                    </div>

                    <div className="rounded-xl border border-border p-4">
                      <p className="mb-3 font-medium text-foreground">Preview</p>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-border">
                              {leadHeaders.map((header) => (
                                <th key={header} className="px-3 py-2 text-left text-muted-foreground">{header}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {leadRows.slice(0, 5).map((row, index) => (
                              <tr key={index} className="border-b border-border/60">
                                {leadHeaders.map((header) => (
                                  <td key={header} className="px-3 py-2 text-foreground">{row[header]}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {step === 3 && (
            <Card className="bg-card border-border">
              <CardHeader>
                <CardTitle>Step 3: Compose Email Sequence</CardTitle>
                <CardDescription>Write your first email and optional follow-up steps.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                {sequenceSteps.map((sequenceStep, index) => (
                  <div key={sequenceStep.step_number} className="rounded-xl border border-border p-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <p className="font-medium text-foreground">Step {sequenceStep.step_number}</p>
                      {sequenceSteps.length > 1 && (
                        <Button variant="ghost" size="icon" onClick={() => removeSequenceStep(index)}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                    <div className="space-y-2">
                      <Label>Subject</Label>
                      <Input value={sequenceStep.subject} onChange={(e) => updateStepData(index, { subject: e.target.value })} />
                    </div>
                    <div className="space-y-2">
                      <Label>Body</Label>
                      <Textarea rows={7} value={sequenceStep.body} onChange={(e) => updateStepData(index, { body: e.target.value })} placeholder="Hi {first_name},&#10;&#10;Wanted to reach out because..." />
                    </div>
                    <div className="space-y-2">
                      <Label>Delay after previous step (hours)</Label>
                      <Input type="number" min="0" value={sequenceStep.delay_hours} onChange={(e) => updateStepData(index, { delay_hours: Number(e.target.value) || 0 })} />
                    </div>
                  </div>
                ))}

                <Button variant="outline" onClick={addSequenceStep}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add Follow-up Step
                </Button>
              </CardContent>
            </Card>
          )}

          {step === 4 && (
            <Card className="bg-card border-border">
              <CardHeader>
                <CardTitle>Step 4: Schedule & Launch Settings</CardTitle>
                <CardDescription>Review the fixed sending policy and choose when the campaign should start.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-2xl border border-border bg-muted/20 p-4">
                  <p className="font-medium text-foreground">Sending policy</p>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    All campaigns send on a fixed schedule: 30 emails per day, evenly spaced, between 3:00 PM and 9:00 PM IST.
                    This slot and limit are locked for every sender to keep delivery behavior consistent.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Scheduled Launch</Label>
                  <Input type="datetime-local" value={formData.send_start_time} onChange={(e) => setFormData({ ...formData, send_start_time: e.target.value })} />
                </div>
                <div className="rounded-xl border border-border p-4 text-sm text-muted-foreground">
                  The system automatically spaces sends at roughly one email every 12 minutes during the active window.
                </div>
              </CardContent>
            </Card>
          )}

          <div className="flex items-center justify-between">
            <Button variant="outline" onClick={() => setStep((current) => Math.max(1, current - 1) as WizardStep)} disabled={step === 1}>
              Back
            </Button>
            {step < 4 ? (
              <Button onClick={() => setStep((current) => Math.min(4, current + 1) as WizardStep)} disabled={!canContinue()}>
                Continue
                <ChevronRight className="ml-2 h-4 w-4" />
              </Button>
            ) : (
              <Button onClick={handleSubmit} disabled={loading}>
                {loading ? "Creating..." : "Create Campaign"}
              </Button>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <Card className="bg-card border-border sticky top-28">
            <CardHeader>
              <CardTitle>Live Preview</CardTitle>
              <CardDescription>How the current message step will look to a recipient</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-xl border border-border p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">From</p>
                <p className="mt-1 text-foreground">You via SendFlow</p>
              </div>
              <div className="rounded-xl border border-border p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Subject</p>
                <p className="mt-1 text-foreground">{activePreview?.subject || formData.subject_template || "Your subject line preview will appear here"}</p>
              </div>
              <div className="rounded-xl border border-border bg-muted/20 p-4 whitespace-pre-wrap text-sm text-foreground">
                {(activePreview?.body || "Hi {first_name},\n\nYour email body preview will appear here.")
                  .replaceAll("{first_name}", "Alex")
                  .replaceAll("{name}", "Alex Johnson")
                  .replaceAll("{company}", "Acme Labs")}
              </div>
              <div className="rounded-xl border border-border p-4 text-sm text-muted-foreground">
                Lead rows loaded: <span className="text-foreground">{leadRows.length}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default CreateCampaign;
