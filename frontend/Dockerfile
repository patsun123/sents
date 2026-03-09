# Stage 1: build
# Node 20 LTS compiles the React/Vite app into optimised static assets
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
# npm ci installs the exact locked versions — no surprises in CI or prod
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: serve
# nginx:alpine is a minimal (~8 MB) image; only the compiled dist/ is copied across
FROM nginx:alpine AS runner
COPY --from=builder /app/dist /usr/share/nginx/html

# Custom nginx config handles SPA routing (all unknown paths → index.html)
# and sets long-lived cache headers for fingerprinted static assets
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf

# Non-root user (TASK-OPS03): nginx:alpine ships a built-in 'nginx' group;
# we add a dedicated unprivileged user and run nginx under it
RUN addgroup -S appgroup && adduser -S appuser -G appgroup \
    && mkdir -p /var/cache/nginx/client_temp \
                /var/cache/nginx/proxy_temp \
                /var/cache/nginx/fastcgi_temp \
                /var/cache/nginx/uwsgi_temp \
                /var/cache/nginx/scgi_temp \
    && chown -R appuser:appgroup /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown appuser:appgroup /var/run/nginx.pid
USER appuser

EXPOSE 80
