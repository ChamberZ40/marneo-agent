FROM python:3.11-slim

# Non-root user
RUN useradd -m -u 1000 marneo
WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || true

# Copy source
COPY marneo/ marneo/
RUN pip install --no-cache-dir -e .

# Data directory
RUN mkdir -p /home/marneo/.marneo && chown -R marneo:marneo /home/marneo
USER marneo
ENV HOME=/home/marneo

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

EXPOSE 8765

CMD ["python", "-m", "marneo", "gateway", "start", "--fg"]
