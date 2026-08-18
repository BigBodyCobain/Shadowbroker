# ---- Stage 1: Compile privacy-core Rust library ----
FROM --platform=$BUILDPLATFORM rust:1.88-slim-bookworm AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    pkg-config \
    libssl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV CARGO_NET_GIT_FETCH_WITH_CLI=true
ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse

COPY privacy-core /build/privacy-core
WORKDIR /build/privacy-core
RUN cargo build --release --lib \
    && ls -la target/release/libprivacy_core.so

# ---- Stage 2: Python backend ----
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install Node.js (for AIS WebSocket proxy), curl (for network fallback), and
# Tor (for Wormhole/remote-agent .onion transport).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    tor \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install UV for fast, reproducible Python dependency management
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin:$PATH"
# Install into system Python (no venv needed inside container)
ENV UV_PROJECT_ENVIRONMENT=/usr/local

# Playwright installs browsers under the current user's cache by default. The
# dependency install below runs as root while the backend runs as backenduser,
# which caused runtime Playwright to look in /app/.cache for a browser that had
# actually been baked under /root/.cache (#516). Use one image-wide location
# that is readable by the non-root runtime user.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Copy workspace root files for UV resolution (build context is repo root)
COPY pyproject.toml /workspace/pyproject.toml
COPY uv.lock /workspace/uv.lock
COPY backend/pyproject.toml /workspace/backend/pyproject.toml

# Install Python dependencies using the lockfile
RUN cd /workspace/backend && uv sync --frozen --no-dev --extra road-corridor \
    && playwright install --with-deps chromium \
    && playwright install chromium-headless-shell \
    && chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"

# Copy backend source code
COPY backend/ .

# Preserve safe static data outside /app/data. The compose named volume mounted
# at /app/data hides image-baked files on first run, so the entrypoint seeds
# missing static JSON into fresh volumes before the backend starts.
RUN mkdir -p /app/image-data \
    && if [ -d /app/data ]; then cp -a /app/data/. /app/image-data/; fi \
    && chmod +x /app/docker-entrypoint.sh

# Install Node.js dependencies (ws module for AIS WebSocket proxy)
COPY backend/package*.json ./
RUN npm ci --omit=dev

# Clean up workspace scaffold
RUN rm -rf /workspace

# Copy compiled privacy-core library from Rust builder stage
COPY --from=rust-builder /build/privacy-core/target/release/libprivacy_core.so /app/libprivacy_core.so
ENV PRIVACY_CORE_LIB=/app/libprivacy_core.so

# Create a non-root user for security
# Grant write access to /app so the auto-updater can extract files
# Pre-create /app/data so mounted volumes inherit correct ownership
RUN adduser --system --uid 1001 --home /app backenduser \
    && mkdir -p /app/data \
    && chown -R backenduser /app \
    && chmod -R u+w /app

# Switch to the non-root user
USER backenduser

# Build-time packaging assertion for #516. Do not launch Chromium here because
# multi-arch image builds may run under emulation; instead verify that the exact
# runtime user resolves an executable Chromium and that the headless-shell
# bundle used by headless launches is present and executable.
RUN python -c "import os; from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); path=p.chromium.executable_path; assert os.path.isfile(path), path; assert os.access(path, os.X_OK), path; shells=list(Path(os.environ['PLAYWRIGHT_BROWSERS_PATH']).glob('chromium_headless_shell-*/**/headless_shell')); assert any(s.is_file() and os.access(s, os.X_OK) for s in shells), shells; print('Playwright runtime browser:', path, 'headless-shell:', shells[0]); p.stop()"

# Expose port
EXPOSE 8000

# Start FastAPI server
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120"]
