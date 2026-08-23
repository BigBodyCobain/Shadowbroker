FROM node:20-alpine AS base

FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/frontend/node_modules ./frontend/node_modules
COPY qdev-project.json ./qdev-project.json
COPY frontend ./frontend
WORKDIR /app/frontend
ENV NEXT_TELEMETRY_DISABLED=1
ARG SHADOWBROKER_SOURCE_REVISION=unknown
ARG SHADOWBROKER_SOURCE_DIRTY=true
ARG SHADOWBROKER_RUNTIME_REVISION=""
ENV SHADOWBROKER_SOURCE_REVISION=$SHADOWBROKER_SOURCE_REVISION
ENV SHADOWBROKER_SOURCE_DIRTY=$SHADOWBROKER_SOURCE_DIRTY
ENV SHADOWBROKER_RUNTIME_REVISION=$SHADOWBROKER_RUNTIME_REVISION
# NEXT_PUBLIC_* vars must exist at build time for Next.js to inline them.
# Default empty = auto-detect from browser hostname at runtime.
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_PUBLIC_READ_ONLY=false
ENV NEXT_PUBLIC_PUBLIC_READ_ONLY=$NEXT_PUBLIC_PUBLIC_READ_ONLY
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/frontend/public ./public

RUN mkdir .next
RUN chown nextjs:nodejs .next

COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
