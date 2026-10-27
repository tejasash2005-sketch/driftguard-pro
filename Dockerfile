FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples
RUN python -m pip install --upgrade pip && python -m pip install .

RUN useradd --create-home --uid 1000 driftguard \
    && mkdir /data && chown driftguard /data
USER driftguard

# Runs persist in a SQLite file on this volume. Set DRIFTGUARD_API_TOKEN (>=16 chars) at
# runtime to require a bearer token; never bake it into the image.
ENV DRIFTGUARD_DB=/data/driftguard.db
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

# API keys, if ever needed for `driftguard record`, are passed at runtime via
# environment variables (-e OPENAI_API_KEY=...). They are never baked into the image.
CMD ["uvicorn", "driftguard.api:app", "--host", "0.0.0.0", "--port", "8000"]
