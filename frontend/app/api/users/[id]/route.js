import { proxyJson } from "../../_utils/proxy";

export async function PATCH(request, context) {
  const { id } = context.params;
  return proxyJson({
    path: `/api/users/${id}`,
    method: "PATCH",
    cookie: request.headers.get("cookie") || "",
    contentType: "application/json",
    body: await request.text(),
  });
}

export async function DELETE(request, context) {
  const { id } = context.params;
  return proxyJson({
    path: `/api/users/${id}`,
    method: "DELETE",
    cookie: request.headers.get("cookie") || "",
  });
}
