import { NextResponse } from "next/server";

function buildBackendUrl(path) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  return `${backend}${path}`;
}

async function parseUpstreamPayload(response) {
  const contentType = response.headers.get("content-type") || "";
  const raw = await response.text();

  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(raw);
    } catch {
      return {
        ok: false,
        error: `Upstream returned invalid JSON (status ${response.status})`,
      };
    }
  }

  const sample = (raw || "").replace(/\s+/g, " ").trim().slice(0, 180);
  return {
    ok: false,
    error: `Upstream returned non-JSON response (status ${response.status})`,
    detail: sample || null,
  };
}

export async function proxyJson({
  path,
  method = "GET",
  body,
  cookie = "",
  contentType,
  forwardSetCookie = false,
}) {
  let upstream;
  try {
    const headers = { cookie };
    if (contentType) headers["content-type"] = contentType;
    upstream = await fetch(buildBackendUrl(path), {
      method,
      headers,
      body,
      cache: "no-store",
    });
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        error: "Backend is unreachable",
        detail: error?.message || String(error),
      },
      { status: 502 }
    );
  }

  const payload = await parseUpstreamPayload(upstream);
  const nextResponse = NextResponse.json(payload, { status: upstream.status });
  if (forwardSetCookie) {
    const setCookie = upstream.headers.get("set-cookie");
    if (setCookie) nextResponse.headers.set("set-cookie", setCookie);
  }
  return nextResponse;
}
