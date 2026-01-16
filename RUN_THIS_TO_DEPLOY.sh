#!/bin/bash

# ============================================================
# BITBASEL RAILWAY DEPLOYMENT - RUN THIS SCRIPT
# ============================================================

set -e

clear
echo "============================================================"
echo "🚀 BitBasel Backend - Railway Deployment"
echo "============================================================"
echo ""
echo "This script will deploy your backend to Railway."
echo ""

# Check Railway CLI
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI not found!"
    echo ""
    echo "Install it with:"
    echo "  npm i -g @railway/cli"
    echo ""
    exit 1
fi

# Check login
echo "Checking Railway login..."
if ! railway whoami &> /dev/null; then
    echo "❌ Not logged in to Railway"
    echo ""
    echo "Please run:"
    echo "  railway login"
    echo ""
    exit 1
fi

echo "✅ Logged in as: $(railway whoami | head -1)"
echo ""

# Step 1: Initialize Railway project
echo "============================================================"
echo "STEP 1: Initialize Railway Project"
echo "============================================================"
echo ""
echo "Running: railway init"
echo ""
echo "IMPORTANT: When prompted:"
echo "  1. Select: Empty Project"
echo "  2. Enter project name: bitbasel-backend"
echo ""
read -p "Press ENTER to continue..."

railway init

echo ""
echo "✅ Project initialized!"
echo ""

# Step 2: Add PostgreSQL
echo "============================================================"
echo "STEP 2: Add PostgreSQL Database"
echo "============================================================"
echo ""

railway add --database postgresql

echo ""
echo "✅ PostgreSQL database added!"
echo ""

# Step 3: Set environment variables
echo "============================================================"
echo "STEP 3: Configure Environment Variables"
echo "============================================================"
echo ""
echo "Setting all environment variables..."
echo ""

railway variables set SECRET_KEY="0B1rytrChkzawGjS3vAPAVV8-Yht9LGI5tyBhLl3xFA"
railway variables set QR_SECRET_SALT="K1_p7MkQjtEdeXAKIPgoqdtae3nNWgh7gw5Baqp6Npg"
railway variables set ALGORITHM="HS256"
railway variables set ACCESS_TOKEN_EXPIRE_MINUTES="30"
railway variables set REFRESH_TOKEN_EXPIRE_DAYS="7"
railway variables set UPLOAD_DIR="uploads"
railway variables set MAX_FILE_SIZE="10485760"
railway variables set APPLE_TEAM_ID="GDZ9V6T9SF"
railway variables set APPLE_KEY_ID="5Y3L2S8R8R"

railway variables set BASEL_RADIUS_KM="5"

echo ""
echo "✅ All environment variables set!"
echo ""

# Step 4: Deploy
echo "============================================================"
echo "STEP 4: Deploy Application"
echo "============================================================"
echo ""
echo "Deploying to Railway..."
echo ""

railway up

echo ""
echo "✅ Application deployed!"
echo ""

# Step 5: Get domain
echo "============================================================"
echo "STEP 5: Get Your Application URL"
echo "============================================================"
echo ""

DOMAIN=$(railway domain 2>/dev/null || echo "")

if [ -n "$DOMAIN" ]; then
    echo "Your app is available at:"
    echo ""
    echo "  🌐 $DOMAIN"
    echo ""
else
    echo "To get your domain, run:"
    echo "  railway domain"
    echo ""
fi

# Step 6: Instructions for volume
echo "============================================================"
echo "STEP 6: Add Persistent Volume (Manual)"
echo "============================================================"
echo ""
echo "⚠️  IMPORTANT: Add volume for file uploads"
echo ""
echo "1. Open Railway dashboard:"
echo "     railway open"
echo ""
echo "2. Click on your service"
echo "3. Go to 'Volumes' tab"
echo "4. Click '+ New Volume'"
echo "5. Set:"
echo "     Mount Path: /app/uploads"
echo "     Size: 1 GB"
echo "6. Click 'Add'"
echo ""
echo "The service will restart with the volume mounted."
echo ""

# Final instructions
echo "============================================================"
echo "🎉 DEPLOYMENT COMPLETE!"
echo "============================================================"
echo ""
echo "Next Steps:"
echo ""
echo "  1. Add volume (see instructions above)"
echo "  2. View logs:     railway logs"
echo "  3. Open dashboard: railway open"
echo "  4. Test health:   curl \$DOMAIN/health"
echo ""
echo "Your deployment is ready! 🚀"
echo ""
