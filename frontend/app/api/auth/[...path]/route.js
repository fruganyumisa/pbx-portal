import { NextResponse } from "next/server";

async function proxyAuth(request, context, method) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const path = context.params.path.join("/");
  const headers = {
    cookie: request.headers.get("cookie") || "",
    "content-type": request.headers.get("content-type") || "application/json",
  };
  const response = await fetch(`${backend}/api/auth/${path}`, {
    method,
    headers,
    body: method === "GET" ? undefined : await request.text(),
    cache: "no-store",
  });
  const data = await response.json();
  const nextResponse = NextResponse.json(data, { status: response.status });
  const setCookie = response.headers.get("set-cookie");
  if (setCookie) nextResponse.headers.set("set-cookie", setCookie);
  return nextResponse;
}

export async function GET(request, context) {
  return proxyAuth(request, context, "GET");
}

export async function POST(request, context) {
  return proxyAuth(request, context, "POST");
}
