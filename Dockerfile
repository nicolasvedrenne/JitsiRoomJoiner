# syntax=docker/dockerfile:1

FROM node:24-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:mainline-alpine-slim
WORKDIR /usr/share/nginx/html

RUN apk add --no-cache curl ca-certificates

COPY --from=builder /app/dist /usr/share/nginx/html

ENV ICS_URL=""

RUN printf '%s\n' \
  '#!/bin/sh' \
  'set -e' \
  '[ -z "$ICS_URL" ] && exit 0' \
  'TMP=/usr/share/nginx/html/calendar.ics.tmp' \
  'DST=/usr/share/nginx/html/calendar.ics' \
  'curl -fsSL "$ICS_URL" -o "$TMP" && mv "$TMP" "$DST"' \
  > /usr/local/bin/fetch_ics.sh \
  && chmod +x /usr/local/bin/fetch_ics.sh \
  && echo "* * * * * /usr/local/bin/fetch_ics.sh" > /etc/crontabs/root

COPY <<'EOF' /docker-entrypoint.sh
#!/bin/sh
set -e
/usr/local/bin/fetch_ics.sh || true
crond
exec nginx -g 'daemon off;'
EOF

RUN chmod +x /docker-entrypoint.sh

EXPOSE 80
CMD ["/docker-entrypoint.sh"]
