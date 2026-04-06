# ─────────────────────────────────────────────
# Base image
# ─────────────────────────────────────────────
FROM python:3.11-slim

# Evitar prompts interactivos durante apt
ENV DEBIAN_FRONTEND=noninteractive

# ─────────────────────────────────────────────
# Dependencias del sistema
# ─────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────
# Directorio de trabajo
# ─────────────────────────────────────────────
WORKDIR /app

# ─────────────────────────────────────────────
# Dependencias Python
# ─────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────
# Código fuente
# ─────────────────────────────────────────────
COPY app.py .
COPY login_grouplac.py .

# ─────────────────────────────────────────────
# Configuración de Streamlit (sin browser auto-open)
# ─────────────────────────────────────────────
RUN mkdir -p /root/.streamlit
COPY .streamlit/config.toml /root/.streamlit/config.toml

# ─────────────────────────────────────────────
# Puerto expuesto
# ─────────────────────────────────────────────
EXPOSE 8501

# ─────────────────────────────────────────────
# Healthcheck
# ─────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# ─────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]