FROM node:20-alpine AS build
WORKDIR /app
COPY mtproto-worker/package.json mtproto-worker/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY mtproto-worker/tsconfig.json ./
COPY mtproto-worker/src ./src
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production \
    CHANNELS_CONFIG=/app/config/telegram-channels.yaml
COPY mtproto-worker/package.json mtproto-worker/package-lock.json* ./
RUN npm ci --omit=dev 2>/dev/null || npm install --omit=dev
COPY --from=build /app/dist ./dist
COPY config /app/config
CMD ["node", "dist/index.js"]
