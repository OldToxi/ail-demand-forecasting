FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt gunicorn
COPY backend/ /app/backend/
COPY forecasting/templates/ /app/forecasting/templates/
COPY data/outputs/forecast/ui/ /app/data/outputs/forecast/ui/
ENV FORECAST_OUTPUTS_DIR=/app/data/outputs
WORKDIR /app/backend
EXPOSE 8000
CMD ["gunicorn","config.wsgi:application","--bind","0.0.0.0:8000","--workers","2","--timeout","60"]
