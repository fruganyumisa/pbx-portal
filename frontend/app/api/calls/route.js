import { NextResponse } from "next/server";

export async function GET(request) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const url = new URL(request.url);
  const response = await fetch(`${backend}/api/calls?${url.searchParams.toString()}`, {
    headers: { cookie: request.headers.get("cookie") || "" },
    cache: "no-store",
  });
  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
