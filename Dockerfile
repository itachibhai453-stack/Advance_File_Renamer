# Base Python image
FROM python:3.10-slim-buster

# Install System Dependencies including FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    mediainfo \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Command to run the Telegram Bot
CMD ["python", "bot.py"]
