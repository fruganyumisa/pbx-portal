import { NextResponse } from "next/server";

export async function PATCH(request, context) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const { id } = context.params;
  const response = await fetch(`${backend}/api/users/${id}`, {
    method: "PATCH",
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

export async function DELETE(request, context) {
  const backend = process.env.PBX_API_URL || "http://backend:5000";
  const { id } = context.params;
  const response = await fetch(`${backend}/api/users/${id}`, {
    method: "DELETE",
    headers: {
      cookie: request.headers.get("cookie") || "",
    },
    cache: "no-store",
  });
  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
