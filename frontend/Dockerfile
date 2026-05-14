FROM node:22-bookworm-slim AS builder
WORKDIR /app
# 리라이트 목적지(빌드 시 next.config에 반영). Compose: http://api:8010
ARG API_INTERNAL_URL=http://127.0.0.1:8010
ENV API_INTERNAL_URL=$API_INTERNAL_URL
# 브라우저가 API에 직접 붙을 때만 설정(일반적으로 생략 → /_nemotron_api 프록시)
ARG NEXT_PUBLIC_API_BASE_URL=
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_INTERNAL_URL=http://127.0.0.1:8010
ENV API_INTERNAL_URL=$API_INTERNAL_URL
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
