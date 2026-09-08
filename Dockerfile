# Debian Bookworm Image
FROM python:3.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies and DejaVu system fonts for watermarking
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

# Expose Render default port
EXPOSE 8080

CMD ["python", "bot.py"]
