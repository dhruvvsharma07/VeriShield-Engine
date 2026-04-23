
FROM python:3.10

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . $HOME/app

EXPOSE 7860

# Note: Hugging Face can handle multiple workers, but 1-2 is best for stability
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
