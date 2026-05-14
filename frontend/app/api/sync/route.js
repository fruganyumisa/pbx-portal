import { proxyJson } from "../_utils/proxy";

export async function POST(request) {
  const url = new URL(request.url);
  return proxyJson({
    path: `/api/sync?${url.searchParams.toString()}`,
    method: "POST",
    cookie: request.headers.get("cookie") || "",
  });
}
