FROM python:3.12-slim

WORKDIR /app

# Install minimal OS runtime C dependencies required by OpenCV headless and ONNX Runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

# Install dependencies and force opencv-python-headless so cv2 works without GUI/X11
RUN uv sync --frozen && \
    uv pip uninstall opencv-python opencv-contrib-python 2>/dev/null || true && \
    uv pip install --force-reinstall --no-deps opencv-python-headless

COPY backend ./backend

ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
