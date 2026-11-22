FROM prom/prometheus:v3.5.0
COPY prometheus.yml /etc/prometheus/prometheus.yml
# TSDB lives in the container's ephemeral storage (V1). It is lost when the task is replaced.
CMD ["--config.file=/etc/prometheus/prometheus.yml", \
     "--storage.tsdb.path=/prometheus", \
     "--storage.tsdb.retention.time=2d", \
     "--web.listen-address=127.0.0.1:9090"]
