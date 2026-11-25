# FUTURE USE ONLY: for a Linux server where Docker is allowed. Not used or tested on the dev laptop.
# Build from the repo root:  docker build -f deploy/Dockerfile -t asset-inventory .

FROM node:22-alpine AS web
WORKDIR /srv/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /srv/frontend/dist /srv/frontend/dist
ENV HOST=0.0.0.0 APP_PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "python -m alembic upgrade head && python -m app"]
