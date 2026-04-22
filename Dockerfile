# Use a robust Python base (not slim) since we have 16GB RAM 
# This ensures all C++ build tools for InsightFace are available
FROM python:3.10

# 1. Install system dependencies for OpenCV and InsightFace
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. Set up a non-root user (Hugging Face Requirement)
# The user ID must be 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# 3. Set working directory
WORKDIR $HOME/app

# 4. Copy and install requirements
# We use --chown=user to avoid permission denied errors
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the code
COPY --chown=user . $HOME/app

# 6. Expose the Hugging Face default port
EXPOSE 7860

# 7. Start the engine
# Note: Hugging Face can handle multiple workers, but 1-2 is best for stability
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
