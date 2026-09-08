FROM python:3.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install System Dependencies + Fonts for Watermark Text
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    mediainfo \
    git \
    curl \
    fonts-dejavu-core \
    ttf-bitstream-vera \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
