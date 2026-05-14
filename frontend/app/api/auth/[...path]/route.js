import { proxyJson } from "../../_utils/proxy";

async function proxyAuth(request, context, method) {
  const path = context.params.path.join("/");
  return proxyJson({
    path: `/api/auth/${path}`,
    method,
    cookie: request.headers.get("cookie") || "",
    contentType: request.headers.get("content-type") || "application/json",
    body: method === "GET" ? undefined : await request.text(),
    forwardSetCookie: true,
  });
}

export async function GET(request, context) {
  return proxyAuth(request, context, "GET");
}

export async function POST(request, context) {
  return proxyAuth(request, context, "POST");
}
