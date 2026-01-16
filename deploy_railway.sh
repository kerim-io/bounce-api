#!/bin/bash

# BitBasel Backend - Railway Deployment Script
# This script helps you deploy to Railway step-by-step

set -e

echo "============================================================"
echo "🚀 BitBasel Backend - Railway Deployment"
echo "============================================================"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Generated secrets

if ! command -v railway &> /dev/null; then
    echo -e "${RED}❌ Railway CLI not found!${NC}"
    echo "Install it with: npm i -g @railway/cli"
    exit 1
fi
echo -e "${GREEN}✓ Railway CLI found${NC}"
echo ""

echo -e "${BLUE}Step 2: Check Railway login${NC}"
if ! railway whoami &> /dev/null; then
    echo -e "${YELLOW}⚠️  Not logged in to Railway${NC}"
    echo "Please run: railway login"
    exit 1
fi
echo -e "${GREEN}✓ Logged in to Railway${NC}"
railway whoami
echo ""

echo -e "${BLUE}Step 3: Initialize Railway project${NC}"
echo "This will create a new Railway project..."
echo ""
echo -e "${YELLOW}Please run the following commands manually:${NC}"
echo ""
echo "  railway init"
echo "  # Select: Empty Project"
echo "  # Enter project name: bitbasel-backend"
echo ""
read -p "Press ENTER after you've completed this step..."
echo ""

echo -e "${BLUE}Step 4: Add PostgreSQL database${NC}"
echo -e "${YELLOW}Please run:${NC}"
echo ""
echo "  railway add --database postgresql"
echo ""
read -p "Press ENTER after database is added..."
echo ""

echo -e "${BLUE}Step 5: Set environment variables${NC}"
echo "I'll now configure all required environment variables..."
echo ""

# Set variables one by one
echo "Setting SECRET_KEY..."
railway variables set SECRET_KEY="$SECRET_KEY"

echo "Setting QR_SECRET_SALT..."
railway variables set QR_SECRET_SALT="$QR_SECRET_SALT"

echo "Setting ALGORITHM..."
railway variables set ALGORITHM="HS256"

echo "Setting ACCESS_TOKEN_EXPIRE_MINUTES..."
railway variables set ACCESS_TOKEN_EXPIRE_MINUTES="30"

echo "Setting REFRESH_TOKEN_EXPIRE_DAYS..."
railway variables set REFRESH_TOKEN_EXPIRE_DAYS="7"

echo "Setting UPLOAD_DIR..."
railway variables set UPLOAD_DIR="uploads"

echo "Setting MAX_FILE_SIZE..."
railway variables set MAX_FILE_SIZE="10485760"

echo "Setting Apple Sign-In variables..."
railway variables set APPLE_TEAM_ID="GDZ9V6T9SF"
railway variables set APPLE_KEY_ID="5Y3L2S8R8R"
railway variables set APPLE_CLIENT_ID="com.bitbasel.app"
railway variables set APPLE_REDIRECT_URI="https://bitbasel.app/auth/callback"
railway variables set APPLE_PRIVATE_KEY_BASE64="$APPLE_PRIVATE_KEY_BASE64"

echo "Setting geofence variables..."
railway variables set BASEL_LAT="25.7907"
railway variables set BASEL_LON="-80.1300"
railway variables set BASEL_RADIUS_KM="5"

echo -e "${GREEN}✓ All environment variables set!${NC}"
echo ""

echo -e "${BLUE}Step 6: Deploy application${NC}"
echo "Deploying to Railway..."
railway up --detach

echo ""
echo -e "${GREEN}✓ Deployment initiated!${NC}"
echo ""

echo -e "${BLUE}Step 7: Add persistent volume${NC}"
echo -e "${YELLOW}Please complete this step in the Railway dashboard:${NC}"
echo ""
echo "  1. Go to your Railway dashboard"
echo "  2. Click on your service"
echo "  3. Go to 'Volumes' tab"
echo "  4. Click '+ New Volume'"
echo "  5. Set Mount Path: /app/uploads"
echo "  6. Set Size: 1 GB"
echo "  7. Click 'Add'"
echo ""
echo "The service will restart automatically with the volume."
echo ""

echo "============================================================"
echo -e "${GREEN}🎉 Deployment Configuration Complete!${NC}"
echo "============================================================"
echo ""
echo "Next Steps:"
echo "  1. Monitor deployment: railway logs"
echo "  2. Get URL: railway domain"
echo "  3. Test health: curl https://your-app.railway.app/health"
echo ""
echo "View dashboard: railway open"
echo ""
