FROM python:3.11-slim

# Install Chrome dependencies, Xvfb, DBus and X11 libraries
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    xdg-utils \
    libxshmfence1 \
    xvfb \
    dbus \
    dbus-x11 \
    libxtst6 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    libxss1 \
    libxext6 \
    libnss3-tools \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Configure DBus and machine-id properly
RUN mkdir -p /var/run/dbus && \
    mkdir -p /var/lib/dbus && \
    dbus-uuidgen > /var/lib/dbus/machine-id && \
    ln -sf /var/lib/dbus/machine-id /etc/machine-id

# Install Chrome with sandbox
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r chrome && useradd -r -g chrome -G audio,video chrome \
    && mkdir -p /home/chrome && chown -R chrome:chrome /home/chrome

# Set working directory
WORKDIR /app

# Create a more robust start script
RUN printf '#!/bin/bash\n\
mkdir -p /run/dbus\n\
dbus-daemon --system --fork\n\
Xvfb :99 -screen 0 1024x768x16 -ac &\n\
sleep 2\n\
export DISPLAY=:99\n\
export DBUS_SESSION_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket\n\
exec python main.py\n' > start.sh && chmod +x start.sh

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run the start script
CMD ["./start.sh"]
