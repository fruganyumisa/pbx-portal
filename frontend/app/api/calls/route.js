import { proxyJson } from "../_utils/proxy";

export async function GET(request) {
  const url = new URL(request.url);
  return proxyJson({
    path: `/api/calls?${url.searchParams.toString()}`,
    cookie: request.headers.get("cookie") || "",
  });
}
