import { NextRequest, NextResponse } from "next/server";
import { getLogs } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const limit = Number(req.nextUrl.searchParams.get("limit") || "50");
    const type = req.nextUrl.searchParams.get("type") || "";
    return NextResponse.json(await getLogs(limit, type));
  } catch (e: unknown) {
    return NextResponse.json({ error: e instanceof Error ? e.message : "Unknown" }, { status: 500 });
  }
}
