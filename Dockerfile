# One container: the Python API serves the built React app. Suits Azure Container Apps / App Service.
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt azure-eventhub
COPY backend/ .
COPY --from=web /web/dist /app/frontend/dist
# Pre-build the demo matches (simulation + tracking) into the image so the first viewer doesn't wait.
RUN python -c "from footie.sim.scenarios import SCENARIOS, load_match; [load_match(s) for s in SCENARIOS]"
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
