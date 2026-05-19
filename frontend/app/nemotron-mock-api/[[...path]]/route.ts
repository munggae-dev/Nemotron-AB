import { handleMockRequest } from "@/lib/mock/handlers";
import { isDemoMode } from "@/lib/demo-mode";

export const dynamic = "force-dynamic";

async function readJsonBody(req: Request): Promise<unknown> {
  const ct = req.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) return undefined;
  try {
    return await req.json();
  } catch {
    return undefined;
  }
}

async function dispatch(req: Request, pathSegments: string[] | undefined): Promise<Response> {
  if (!isDemoMode()) {
    return new Response(JSON.stringify({ detail: "데모 모드가 꺼져 있습니다." }), { status: 404 });
  }

  const subpath = pathSegments?.length ? `/${pathSegments.join("/")}` : "";
  const url = new URL(req.url);
  const path = `${subpath}${url.search}`;

  return handleMockRequest({
    method: req.method,
    path,
    searchParams: url.searchParams,
    body: await readJsonBody(req),
  });
}

export async function GET(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path } = await ctx.params;
  return dispatch(req, path);
}

export async function POST(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path } = await ctx.params;
  return dispatch(req, path);
}

export async function PATCH(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path } = await ctx.params;
  return dispatch(req, path);
}

export async function DELETE(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path } = await ctx.params;
  return dispatch(req, path);
}
