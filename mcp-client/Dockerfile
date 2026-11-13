# Built for linux/amd64, the only platform SPCS runs.
FROM node:26-slim
ENV NODE_ENV=production
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY src ./src
COPY public ./public

USER node
ENV HOST=0.0.0.0 \
    PORT=8080
EXPOSE 8080
CMD ["node", "src/index.js"]
