import { NextResponse } from "next/server";

export async function GET() {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const response = await fetch(`${backend}/health`, { cache: "no-store" });
  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
