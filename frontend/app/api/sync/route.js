import { NextResponse } from "next/server";

export async function POST(request) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const url = new URL(request.url);
  const response = await fetch(`${backend}/api/sync?${url.searchParams.toString()}`, {
    method: "POST",
    headers: { cookie: request.headers.get("cookie") || "" },
    cache: "no-store",
  });
  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
