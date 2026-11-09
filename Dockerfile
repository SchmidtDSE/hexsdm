FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as an unprivileged user, as geo-query does (SchmidtDSE/geo-query#458, #462).
# Nothing here needs root: the server listens on 8000 and writes only results
# under SDM_OUTPUT_DIR and spill files under /tmp. The uid is numeric so
# Kubernetes can check runAsNonRoot.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/app app
ENV HOME=/home/app PYTHONDONTWRITEBYTECODE=1
USER 10001

# Installed as the app user, so the extensions land in
# /home/app/.duckdb/extensions where the runtime finds them.
RUN python -c "import duckdb; c = duckdb.connect(); c.sql('INSTALL httpfs; INSTALL h3 FROM community')"

COPY . /app
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA PORT=8000
CMD ["python", "server.py"]
