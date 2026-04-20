import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, LineChart as LineChartIcon, LogOut, Mail, Plus, SendHorizonal, ShieldAlert } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/api/client";
import { useToast } from "@/hooks/use-toast";

const AccountsPage = () => {
  const { accounts, token, switchAccount, logout, login, isAuthenticated, user } = useAuth();
  const { toast } = useToast();
  const [dailyLimit, setDailyLimit] = useState(30);
  const [activity, setActivity] = useState<any[]>([]);
  const [saving, setSaving] = useState(false);
  const [sendingTest, setSendingTest] = useState(false);

  useEffect(() => {
    if (!user) return;
    setDailyLimit(user.daily_limit || 30);
  }, [user]);

  useEffect(() => {
    if (!token || !isAuthenticated) return;
    const load = async () => {
      try {
        const response = await api.getAccountActivity(token);
        setActivity(response.activity || []);
      } catch {
        setActivity([]);
      }
    };
    load();
  }, [isAuthenticated, token]);

  const health = useMemo(() => {
    if (!user) return { score: 0, spamRisk: "Unknown", ageDays: 0 };
    const accountAgeDays = Math.max(
      0,
      Math.floor((Date.now() - new Date(user.created_at).getTime()) / (1000 * 60 * 60 * 24))
    );
    const usageRatio = (user.sent_today || 0) / Math.max(user.daily_limit || 30, 1);
    const score = Math.max(45, Math.min(97, Math.round(92 - usageRatio * 30 + Math.min(accountAgeDays / 20, 8))));
    return {
      score,
      spamRisk: usageRatio > 0.85 ? "High" : usageRatio > 0.6 ? "Medium" : "Low",
      ageDays: accountAgeDays,
    };
  }, [user]);

  const handleSave = async () => {
    if (!token) return;
    setSaving(true);
    try {
      await api.updateAccountSettings(token, { daily_limit: dailyLimit });
      toast({ title: "Settings updated", description: "Daily limit was saved." });
    } catch (err) {
      toast({
        title: "Save failed",
        description: err instanceof Error ? err.message : "Could not save account settings.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleTestSend = async () => {
    if (!token) return;
    setSendingTest(true);
    try {
      await api.sendTestEmail(token);
      toast({ title: "Test sent", description: "A verification email was sent to the active account." });
    } catch (err) {
      toast({
        title: "Test send failed",
        description: err instanceof Error ? err.message : "Could not send the test email.",
        variant: "destructive",
      });
    } finally {
      setSendingTest(false);
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        Connect a Google account from the login screen to manage senders.
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-foreground">Accounts</h1>
          <p className="mt-1 text-muted-foreground">Monitor sender health, adjust the daily limit, and keep the fixed 3 PM to 9 PM IST send window.</p>
        </div>
        <Button onClick={() => login()} className="gradient-accent text-white border-0 hover:opacity-90">
          <Plus className="mr-2 h-4 w-4" />
          Add Google Account
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldAlert className="h-4 w-4" />
              Health Score
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-4xl font-bold text-foreground">{health.score}</p>
            <p className="mt-2 text-sm text-muted-foreground">Spam risk: {health.spamRisk}</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-base">Send Rate</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-4xl font-bold text-foreground">{user?.sent_today || 0}</p>
            <p className="mt-2 text-sm text-muted-foreground">Emails sent today out of {user?.daily_limit || 30}</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-base">Account Age</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-4xl font-bold text-foreground">{health.ageDays}d</p>
            <p className="mt-2 text-sm text-muted-foreground">Based on the date this sender was connected to SendFlow</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <LineChartIcon className="h-4 w-4" />
              Sending Activity
            </CardTitle>
            <CardDescription>Last 7 days of sends and replies for the active account.</CardDescription>
          </CardHeader>
          <CardContent className="h-[280px]">
            {activity.length === 0 ? (
              <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border text-sm text-muted-foreground">
                No sending activity yet. Run a test send or launch a campaign to populate this chart.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={activity}>
                  <XAxis dataKey="date" stroke="#7c7f8d" />
                  <YAxis stroke="#7c7f8d" />
                  <Tooltip />
                  <Line type="monotone" dataKey="sent" stroke="#d946ef" strokeWidth={3} />
                  <Line type="monotone" dataKey="replies" stroke="#38bdf8" strokeWidth={3} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-base">Account Settings</CardTitle>
            <CardDescription>Daily limit is configurable. Campaign send timing stays fixed between 3:00 PM and 9:00 PM IST.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Daily Send Limit</Label>
              <Input type="number" min={1} max={500} value={dailyLimit} onChange={(e) => setDailyLimit(Number(e.target.value || 30))} />
            </div>
            <div className="rounded-xl border border-border p-4 text-sm text-muted-foreground">
              Campaigns still send evenly during the fixed window of 3:00 PM to 9:00 PM IST. Only the daily cap changes here.
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Button onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save Limit"}
              </Button>
              <Button variant="outline" onClick={handleTestSend} disabled={sendingTest}>
                <SendHorizonal className="mr-2 h-4 w-4" />
                {sendingTest ? "Sending..." : "Test Send"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {accounts.map((account) => {
          const isActive = account.token === token;
          return (
            <Card key={account.token} className={`border-border ${isActive ? "border-purple-500/40 bg-purple-500/5" : "bg-card"}`}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base text-foreground">
                  <Mail className="h-4 w-4" />
                  {account.user.email}
                </CardTitle>
                <CardDescription>
                  Daily limit: {account.user.daily_limit || 30} emails • Window: 3:00 PM - 9:00 PM IST
                </CardDescription>
              </CardHeader>
              <CardContent className="flex gap-3">
                <Button
                  variant={isActive ? "secondary" : "outline"}
                  className="flex-1"
                  onClick={() => switchAccount(account.token)}
                >
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  {isActive ? "Active Sender" : "Make Active"}
                </Button>
                <Button
                  variant="outline"
                  className="border-red-600/30 text-red-600 hover:bg-red-600/10"
                  onClick={() => logout(account.token)}
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Logout
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
};

export default AccountsPage;
