# The review UI: the built React app behind nginx, which also forwards every API path
# to the backend and adds the API key there, so the key never reaches the browser.
#   docker build -t tea-web web/
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The real API on the page's own origin (nginx forwards it), never the mock.
ENV VITE_API_MOCK=0
RUN npm run build

FROM nginx:1.27-alpine
# BACKEND_URL: where nginx reaches the API. API_KEY: sent on every forwarded request
# (empty when the API runs without one). The nginx image fills the template at start.
ENV BACKEND_URL=http://backend:8000 API_KEY=""
COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
