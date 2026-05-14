import { proxyJson } from "../../../_utils/proxy";

export async function POST(request, context) {
  const { id } = context.params;
  return proxyJson({
    path: `/api/users/${id}/password`,
    method: "POST",
    cookie: request.headers.get("cookie") || "",
    contentType: "application/json",
    body: await request.text(),
  });
}
