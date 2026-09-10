# Ingress sidecar (see nginx.conf). Built by Cloud Build from deploy/cloudrun/.
# mirror.gcr.io is Google's pull-through mirror of Docker Hub (no rate limits).
FROM mirror.gcr.io/library/nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
