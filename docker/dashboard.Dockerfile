FROM node:22-alpine AS build

WORKDIR /app

COPY src/Frontend/dashboard/package*.json ./
RUN npm ci

COPY src/Frontend/dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY docker/dashboard.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
