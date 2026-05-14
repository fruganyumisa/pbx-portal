import { proxyJson } from "../_utils/proxy";

export async function GET(request) {
  return proxyJson({
    path: "/api/users",
    cookie: request.headers.get("cookie") || "",
  });
}

export async function POST(request) {
  return proxyJson({
    path: "/api/users",
    method: "POST",
    cookie: request.headers.get("cookie") || "",
    contentType: "application/json",
    body: await request.text(),
  });
}
