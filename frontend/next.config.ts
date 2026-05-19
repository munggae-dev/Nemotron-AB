import type { NextConfig } from "next";

/** 서버(Next)가 FastAPI로 프록시할 때 사용. Docker 등에서는 http://api:8010 형태로 지정 */
const internalApi =
  process.env.API_INTERNAL_URL?.replace(/\/$/, "") || "http://127.0.0.1:8010";

const isDemo = process.env.NEXT_PUBLIC_DEMO_MODE === "1" || process.env.NEXT_PUBLIC_DEMO_MODE === "true";
const isStaticDemo =
  process.env.NEXT_PUBLIC_DEMO_STATIC === "1" || process.env.NEXT_PUBLIC_DEMO_STATIC === "true";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH?.replace(/\/$/, "") ?? "";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: isStaticDemo ? "export" : "standalone",
  basePath: basePath || undefined,
  assetPrefix: basePath ? `${basePath}/` : undefined,
  trailingSlash: isStaticDemo ? true : undefined,
  images: { unoptimized: isStaticDemo },
};

if (!isStaticDemo) {
  nextConfig.rewrites = async () => {
    if (isDemo) return [];
    return [
      {
        source: "/_nemotron_api/:path*",
        destination: `${internalApi}/:path*`,
      },
    ];
  };
}

export default nextConfig;
