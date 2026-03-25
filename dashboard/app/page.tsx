"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";

// --- Types ---
interface Stats {
  totalGroups: number;
  totalReplies: number;
  totalLogs: number;
  latestRound: {
    round: number;
    keyword: string;
    groups_found: number;
    replies_sent: number;
    elapsed_sec: number;
    created_at: string;
  } | null;
  lastActivity: string | null;
  status: string;
  tokens?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    api_calls: number;
    cost_usd: number;
    cost_thb: number;
  } | null;
}

interface LogEntry {
  _id: string;
  ts: string;
  type: string;
  message?: string;
  reason?: string;
  action?: string;
  phase?: string;
  keyword?: string;
  step?: number;
  screenshot?: string;
  group?: string;
  post_summary?: string;
  reply_text?: string;
  should_reply?: boolean;
  count?: number;
  round?: number;
}

interface Group {
  _id: string;
  name: string;
  url: string;
  members: string;
  privacy: string;
  keyword: string;
}

interface Reply {
  _id: string;
  group: string;
  post_url: string;
  post_summary: string;
  reply_text: string;
  replied_at?: string;
  created_at?: string;
}

// --- Helpers ---
function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "เมื่อกี้";
  if (mins < 60) return `${mins} นาทีที่แล้ว`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} ชม.ที่แล้ว`;
  return `${Math.floor(hrs / 24)} วันที่แล้ว`;
}

function typeBadge(type: string) {
  const colors: Record<string, string> = {
    action: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    replied: "bg-green-500/20 text-green-400 border-green-500/30",
    error: "bg-red-500/20 text-red-400 border-red-500/30",
    phase: "bg-purple-500/20 text-purple-400 border-purple-500/30",
    extract: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    round_start: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
    round_end: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
    enter_group: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    post_analyzed: "bg-indigo-500/20 text-indigo-400 border-indigo-500/30",
    startup: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  };
  return colors[type] || "bg-zinc-500/20 text-zinc-400 border-zinc-500/30";
}

function logMessage(log: LogEntry): string {
  if (log.message) return log.message;
  if (log.reason) return log.reason;
  if (log.type === "extract") return `ดึงข้อมูล ${log.count || 0} รายการ`;
  if (log.type === "phase") return `${log.phase} — ${log.keyword || log.group || ""}`;
  return log.type;
}

// --- Components ---
function StatCard({ title, value, sub }: { title: string; value: string | number; sub?: string }) {
  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader className="pb-2">
        <CardDescription className="text-zinc-500 text-xs uppercase tracking-wider">{title}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold text-zinc-100 font-mono">{value}</div>
        {sub && <p className="text-xs text-zinc-500 mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function LiveLog({ logs }: { logs: LogEntry[] }) {
  return (
    <Card className="bg-zinc-900 border-zinc-800 col-span-full">
      <CardHeader>
        <CardTitle className="text-zinc-100 flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          Live Activity
        </CardTitle>
        <CardDescription className="text-zinc-500">กิจกรรมล่าสุดของ AI Agent</CardDescription>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[400px] pr-4">
          <div className="space-y-2">
            {logs.map((log) => (
              <div key={log._id} className="flex items-start gap-3 py-2 border-b border-zinc-800/50 last:border-0">
                <div className="text-xs text-zinc-600 font-mono w-16 shrink-0 pt-0.5">
                  {new Date(log.ts).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </div>
                <Badge variant="outline" className={`text-[10px] px-1.5 py-0 shrink-0 ${typeBadge(log.type)}`}>
                  {log.type}
                </Badge>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-zinc-300 truncate">{logMessage(log)}</p>
                  {log.group && (
                    <p className="text-xs text-zinc-600 mt-0.5">กลุ่ม: {log.group}</p>
                  )}
                </div>
                {log.step !== undefined && (
                  <span className="text-xs text-zinc-600 font-mono">#{log.step}</span>
                )}
              </div>
            ))}
            {logs.length === 0 && (
              <p className="text-zinc-600 text-sm text-center py-8">ยังไม่มี activity</p>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

function GroupList({ groups }: { groups: Group[] }) {
  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100">กลุ่มที่พบ</CardTitle>
        <CardDescription className="text-zinc-500">{groups.length} กลุ่ม</CardDescription>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[300px]">
          <div className="space-y-3">
            {groups.map((g) => (
              <div key={g._id} className="border border-zinc-800 rounded-lg p-3">
                <a
                  href={g.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-blue-400 hover:text-blue-300 hover:underline block truncate"
                >
                  {g.name}
                </a>
                <div className="flex gap-2 mt-1.5">
                  <Badge variant="outline" className="text-[10px] bg-zinc-800 text-zinc-400 border-zinc-700">
                    {g.members} สมาชิก
                  </Badge>
                  <Badge variant="outline" className={`text-[10px] ${g.privacy === "public" ? "bg-green-900/30 text-green-400 border-green-800" : "bg-yellow-900/30 text-yellow-400 border-yellow-800"}`}>
                    {g.privacy}
                  </Badge>
                  <Badge variant="outline" className="text-[10px] bg-zinc-800 text-zinc-500 border-zinc-700">
                    {g.keyword}
                  </Badge>
                </div>
              </div>
            ))}
            {groups.length === 0 && <p className="text-zinc-600 text-sm text-center py-4">ยังไม่มีกลุ่ม</p>}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

function ReplyList({ replies }: { replies: Reply[] }) {
  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100">ข้อความที่ตอบ</CardTitle>
        <CardDescription className="text-zinc-500">{replies.length} ข้อความ</CardDescription>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[300px]">
          <div className="space-y-3">
            {replies.map((r) => (
              <div key={r._id} className="border border-zinc-800 rounded-lg p-3">
                <p className="text-xs text-zinc-500 mb-1">กลุ่ม: {r.group}</p>
                <p className="text-xs text-zinc-400 mb-2">โพสต์: {r.post_summary}</p>
                <Separator className="bg-zinc-800 my-2" />
                <p className="text-sm text-emerald-400">&ldquo;{r.reply_text}&rdquo;</p>
                <div className="flex justify-between mt-2">
                  {r.post_url && (
                    <a href={r.post_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-blue-500 hover:underline">
                      ดูโพสต์
                    </a>
                  )}
                  <span className="text-[10px] text-zinc-600">
                    {r.replied_at ? timeAgo(r.replied_at) : r.created_at ? timeAgo(r.created_at) : ""}
                  </span>
                </div>
              </div>
            ))}
            {replies.length === 0 && <p className="text-zinc-600 text-sm text-center py-4">ยังไม่มีข้อความ</p>}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

// --- Main ---
export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [replies, setReplies] = useState<Reply[]>([]);

  const fetchAll = useCallback(async () => {
    try {
      const [s, l, g, r] = await Promise.all([
        fetch("/api/stats").then((res) => res.json()),
        fetch("/api/logs?limit=50").then((res) => res.json()),
        fetch("/api/groups").then((res) => res.json()),
        fetch("/api/replies").then((res) => res.json()),
      ]);
      setStats(s);
      if (Array.isArray(l)) setLogs(l);
      if (Array.isArray(g)) setGroups(g);
      if (Array.isArray(r)) setReplies(r);
    } catch {
      /* retry next interval */
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="border-b border-zinc-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">FB Scanner Monitor</h1>
            <p className="text-xs text-zinc-500 mt-0.5">AI Agent — Real-time Dashboard</p>
          </div>
          <div className="flex items-center gap-3">
            {stats?.lastActivity && (
              <span className="text-xs text-zinc-500">อัปเดต: {timeAgo(stats.lastActivity)}</span>
            )}
            <Badge
              variant="outline"
              className={stats?.status === "running"
                ? "bg-green-500/10 text-green-400 border-green-500/30"
                : "bg-zinc-500/10 text-zinc-500 border-zinc-700"}
            >
              <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${stats?.status === "running" ? "bg-green-500 animate-pulse" : "bg-zinc-600"}`} />
              {stats?.status === "running" ? "Running" : "Idle"}
            </Badge>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard title="กลุ่มที่พบ" value={stats?.totalGroups ?? "—"} />
          <StatCard title="ข้อความที่ตอบ" value={stats?.totalReplies ?? "—"} />
          <StatCard title="Total Actions" value={stats?.totalLogs ?? "—"} />
          <StatCard
            title="AI Calls"
            value={stats?.tokens?.api_calls ?? "—"}
            sub={stats?.tokens ? `${stats.tokens.total_tokens.toLocaleString()} tokens` : undefined}
          />
          <StatCard
            title="ค่าใช้จ่าย"
            value={stats?.tokens ? `฿${stats.tokens.cost_thb}` : "—"}
            sub={stats?.tokens ? `$${stats.tokens.cost_usd} USD` : undefined}
          />
        </div>

        <LiveLog logs={logs} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <GroupList groups={groups} />
          <ReplyList replies={replies} />
        </div>
      </main>
    </div>
  );
}
