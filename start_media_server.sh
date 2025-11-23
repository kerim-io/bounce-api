#!/bin/bash
# Start the BitBasel C++ Media Server

cd "$(dirname "$0")/media_server_cpp/build"

echo "Starting BitBasel Media Server on port 8082..."
./media_server
