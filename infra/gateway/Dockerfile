# Gateway image: unprivileged nginx (multi-arch, includes linux/s390x) with the
# static frontend baked in. Build context: repository root.
FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY infra/gateway/nginx.conf /etc/nginx/conf.d/default.conf
COPY infra/gateway/proxy_params.conf /etc/nginx/proxy_params.conf
COPY frontend/ /usr/share/nginx/html/
EXPOSE 8443
