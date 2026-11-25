FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV SENTINEL_HOME=/data
VOLUME /data
ENTRYPOINT ["python", "-m", "sentinel"]
CMD ["daemon"]
