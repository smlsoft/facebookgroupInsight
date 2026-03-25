import { MongoClient, Db } from "mongodb";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const uri = process.env.MONGODB_URI || "";
const dbName = process.env.MONGODB_DB || "fb_scanner";
const AGENT_OUTPUT = process.env.AGENT_OUTPUT || join(process.cwd(), "..", "output");

let client: MongoClient | null = null;
let db: Db | null = null;
let mongoFailed = false;

export async function getDb(): Promise<Db | null> {
  if (mongoFailed) return null;
  if (db) return db;
  if (!uri) { mongoFailed = true; return null; }

  try {
    client = new MongoClient(uri, { serverSelectionTimeoutMS: 5000 });
    await client.connect();
    db = client.db(dbName);
    return db;
  } catch {
    mongoFailed = true;
    return null;
  }
}

// --- JSONL Fallback ---
function readJsonl(filename: string): Record<string, unknown>[] {
  const path = join(AGENT_OUTPUT, filename);
  if (!existsSync(path)) return [];
  try {
    const lines = readFileSync(path, "utf-8").trim().split("\n");
    return lines
      .filter((l) => l.trim())
      .map((l, i) => {
        try {
          const obj = JSON.parse(l);
          return { ...obj, _id: obj._id || `local_${i}` };
        } catch {
          return null;
        }
      })
      .filter(Boolean) as Record<string, unknown>[];
  } catch {
    return [];
  }
}

function readJsonFiles(pattern: string): Record<string, unknown>[] {
  const fs = require("fs");
  const path = require("path");
  const dir = AGENT_OUTPUT;
  if (!existsSync(dir)) return [];
  try {
    const files: string[] = fs.readdirSync(dir)
      .filter((f: string) => f.startsWith(pattern) && f.endsWith(".json"))
      .sort()
      .reverse();
    const result: Record<string, unknown>[] = [];
    for (const f of files.slice(0, 10)) {
      try {
        const data = JSON.parse(readFileSync(join(dir, f), "utf-8"));
        if (Array.isArray(data)) {
          data.forEach((item: Record<string, unknown>, i: number) =>
            result.push({ ...item, _id: item._id || `${f}_${i}` })
          );
        }
      } catch { /* skip */ }
    }
    return result;
  } catch {
    return [];
  }
}

export async function getLogs(limit = 50, type = ""): Promise<Record<string, unknown>[]> {
  const db = await getDb();
  if (db) {
    const filter: Record<string, unknown> = {};
    if (type) filter.type = type;
    const docs = await db.collection("agent_logs").find(filter).sort({ ts: -1 }).limit(limit).toArray();
    return docs.map((d) => ({ ...d, _id: d._id.toString() }));
  }
  // JSONL fallback
  let logs = readJsonl("agent_log.jsonl");
  if (type) logs = logs.filter((l) => l.type === type);
  return logs.reverse().slice(0, limit);
}

export async function getGroups(): Promise<Record<string, unknown>[]> {
  const db = await getDb();
  if (db) {
    const docs = await db.collection("groups").find({}).sort({ updated_at: -1 }).limit(100).toArray();
    return docs.map((d) => ({ ...d, _id: d._id.toString() }));
  }
  return readJsonFiles("groups_");
}

export async function getReplies(): Promise<Record<string, unknown>[]> {
  const db = await getDb();
  if (db) {
    const docs = await db.collection("replies").find({}).sort({ created_at: -1 }).limit(100).toArray();
    return docs.map((d) => ({ ...d, _id: d._id.toString() }));
  }
  // Fallback: อ่าน replies จาก JSON files + agent_log.jsonl (type=replied)
  const fromFiles = readJsonFiles("replies_");
  const fromLog = readJsonl("agent_log.jsonl")
    .filter((l) => l.type === "replied")
    .map((l, i) => ({ ...l, _id: l._id || `reply_log_${i}` }));
  // Merge + dedup by post_url
  const seen = new Set<string>();
  const all: Record<string, unknown>[] = [];
  for (const r of [...fromLog, ...fromFiles]) {
    const key = (r.post_url as string) || `${r.group}_${r.reply_text}`;
    if (!seen.has(key)) {
      seen.add(key);
      all.push(r);
    }
  }
  return all;
}

export async function getStats() {
  const db = await getDb();
  if (db) {
    const [totalGroups, totalReplies, totalLogs, latestRound, recentLogs] = await Promise.all([
      db.collection("groups").countDocuments(),
      db.collection("replies").countDocuments(),
      db.collection("agent_logs").countDocuments(),
      db.collection("rounds").findOne({}, { sort: { created_at: -1 } }),
      db.collection("agent_logs").find({}).sort({ ts: -1 }).limit(1).toArray(),
    ]);
    return {
      totalGroups, totalReplies, totalLogs,
      latestRound: latestRound ? { round: latestRound.round, keyword: latestRound.keyword, groups_found: latestRound.groups_found, replies_sent: latestRound.replies_sent, elapsed_sec: latestRound.elapsed_sec, created_at: latestRound.created_at } : null,
      lastActivity: recentLogs[0]?.ts || null,
      status: recentLogs[0]?.ts ? "running" : "idle",
      source: "mongodb",
    };
  }
  // JSONL fallback
  const logs = readJsonl("agent_log.jsonl");
  const groups = readJsonFiles("groups_");
  const repliedLogs = logs.filter((l) => l.type === "replied");
  const lastLog = logs.length > 0 ? logs[logs.length - 1] : null;

  // Token usage จาก logs (round_end หรือ token_update)
  const tokenLogs = logs.filter((l) => l.tokens || (l.type === "token_update" && l.tokens));
  const lastTokenLog = tokenLogs.length > 0 ? tokenLogs[tokenLogs.length - 1] : null;

  return {
    totalGroups: groups.length,
    totalReplies: repliedLogs.length,
    tokens: lastTokenLog?.tokens || null,
    totalLogs: logs.length,
    latestRound: null,
    lastActivity: lastLog?.ts || null,
    status: lastLog?.ts ? "running" : "idle",
    source: "jsonl",
  };
}
