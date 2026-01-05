# Dockerfile for BitBasel mediasoup Media Server
# Much simpler than C++ build - no WebRTC compilation required!

FROM node:18-bullseye-slim AS builder

# Install build dependencies for mediasoup
RUN apt-get update && apt-get install -y \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files
COPY package*.json ./
COPY tsconfig.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY src/ ./src/

# Build TypeScript
RUN npm run build

# Production stage
FROM node:18-bullseye-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files and install production dependencies only
COPY package*.json ./
RUN npm ci --only=production

# Copy compiled code from builder
COPY --from=builder /app/dist ./dist
COPY config.json ./

# Create directories
RUN mkdir -p logs

# Expose ports
# 9001: HTTP API
# 9002: WebSocket signaling
# 40000-49999: mediasoup RTC ports
EXPOSE 9001 9002
EXPOSE 40000-49999/udp
EXPOSE 40000-49999/tcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD node -e "require('http').get('http://localhost:9001/health', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))"

# Start the server
CMD ["node", "dist/server.js"]
