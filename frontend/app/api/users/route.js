import { NextResponse } from "next/server";

export async function GET(request) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const response = await fetch(`${backend}/api/users`, {
    headers: { cookie: request.headers.get("cookie") || "" },
    cache: "no-store",
  });
  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}

export async function POST(request) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const response = await fetch(`${backend}/api/users`, {
    method: "POST",
    headers: {
      cookie: request.headers.get("cookie") || "",
      "content-type": "application/json",
    },
    body: await request.text(),
    cache: "no-store",
  });
  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
