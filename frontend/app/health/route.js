import { proxyJson } from "../api/_utils/proxy";

export async function GET() {
  return proxyJson({ path: "/health" });
}
