# Fixture stub: serves recorded, scrubbed XMLA responses (no host, no secrets).
FROM python:3.10-slim
WORKDIR /app
COPY docker/ssas-stub/stub.py /app/stub.py
COPY tests/fixtures /tests/fixtures
ENV PYTHONUNBUFFERED=1
ENV SSAS_STUB_FIXTURES=/tests/fixtures/xmla
EXPOSE 8080
CMD ["python", "/app/stub.py", "8080"]
