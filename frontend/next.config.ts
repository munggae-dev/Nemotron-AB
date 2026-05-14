import type { NextConfig } from "next";

/** 서버(Next)가 FastAPI로 프록시할 때 사용. Docker 등에서는 http://api:8010 형태로 지정 */
const internalApi =
  process.env.API_INTERNAL_URL?.replace(/\/$/, "") || "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    // 브라우저는 기본적으로 이 경로만 사용(동일 Origin). 포트포워딩 3000만 열어도 API 연결 가능.
    // NEXT_PUBLIC_API_BASE_URL 을 직접 쓰면 이 프록시는 요청에 사용되지 않음.
    return [
      {
        source: "/_nemotron_api/:path*",
        destination: `${internalApi}/:path*`,
      },
    ];
  },
};

export default nextConfig;
