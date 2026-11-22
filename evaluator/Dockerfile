# Build context: repository root (the image needs ../data).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DELUSION_DATA_DIR=/app/data

WORKDIR /app
COPY evaluator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --system --uid 10001 evaluator

COPY evaluator/delusion_monitor ./delusion_monitor
COPY data ./data

USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
ENTRYPOINT ["python", "-m", "delusion_monitor"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
