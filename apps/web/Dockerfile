FROM node:24-slim AS build
RUN corepack enable
WORKDIR /app
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @terrasentry/web build

FROM node:24-slim
ENV NODE_ENV=production PORT=3000
WORKDIR /app
COPY --from=build /app/apps/web/.output ./.output
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
