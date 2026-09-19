#!/bin/bash
set -e

# ============================================================
# Runpod Endpoint Setup Script
# ============================================================
# This script creates secrets and updates your Runpod endpoint
# with the transcription-transcription serverless image.
#
# USAGE:
#   1. Add your Runpod API key below
#   2. chmod +x setup_runpod_endpoint.sh
#   3. ./setup_runpod_endpoint.sh
# ============================================================

# Load API key from .env
if [ -f .env ]; then
    source .env
fi

# Validate API key
if [ -z "$RUNPOD_API_KEY" ]; then
    echo "Error: RUNPOD_API_KEY is not set in .env file."
    exit 1
fi

# Configuration
ENDPOINT_ID="9hhc01z23ocyfr"
IMAGE="leandrodisconzi/transcription-transcription:serverless"
GPU_TYPE="NVIDIA RTX A6000"  # 48GB Pro
GPU_COUNT=1
EPHEMERAL_STORAGE_GB=5
CONTAINER_PORT=8049
START_CMD="python -u src/runpod_handler.py"

# Load tokens from .env
if [ -f .env ]; then
    source .env
else
    echo "Error: .env file not found"
    exit 1
fi

# Validate API key
if [ -z "$RUNPOD_API_KEY" ]; then
    echo "Error: RUNPOD_API_KEY is not set. Please add it to the script."
    exit 1
fi

echo "============================================================"
echo "Setting up Runpod Endpoint: $ENDPOINT_ID"
echo "============================================================"

# Step 1: Create or update secrets
echo ""
echo "Step 1: Creating/updating secrets..."

# Create PYANNOTE_AUTH_TOKEN secret
echo "  - Creating PYANNOTE_AUTH_TOKEN secret..."
PYANNOTE_SECRET_RESPONSE=$(curl -s -X POST "https://api.runpod.io/graphql" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"mutation { saveSecretValue(input: { name: \\\"PYANNOTE_AUTH_TOKEN\\\", value: \\\"$PYANNOTE_AUTH_TOKEN\\\" }) { id name } }\"
  }")

echo "    Response: $PYANNOTE_SECRET_RESPONSE"

# Create HUGGINGFACE_HUB_TOKEN secret
echo "  - Creating HUGGINGFACE_HUB_TOKEN secret..."
HF_SECRET_RESPONSE=$(curl -s -X POST "https://api.runpod.io/graphql" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"mutation { saveSecretValue(input: { name: \\\"HUGGINGFACE_HUB_TOKEN\\\", value: \\\"$HUGGINGFACE_HUB_TOKEN\\\" }) { id name } }\"
  }")

echo "    Response: $HF_SECRET_RESPONSE"

# Step 2: Update endpoint
echo ""
echo "Step 2: Updating endpoint configuration..."

UPDATE_RESPONSE=$(curl -s -X POST "https://api.runpod.io/graphql" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"mutation {
      updateEndpointTemplate(
        input: {
          endpointId: \\\"$ENDPOINT_ID\\\",
          imageName: \\\"$IMAGE\\\",
          dockerArgs: \\\"$START_CMD\\\",
          containerDiskInGb: $EPHEMERAL_STORAGE_GB,
          ports: \\\"8049/http\\\",
          env: [
            { key: \\\"PYANNOTE_AUTH_TOKEN\\\", value: \\\"{{PYANNOTE_AUTH_TOKEN}}\\\" },
            { key: \\\"HF_TOKEN\\\", value: \\\"{{PYANNOTE_AUTH_TOKEN}}\\\" },
            { key: \\\"HUGGINGFACE_HUB_TOKEN\\\", value: \\\"{{HUGGINGFACE_HUB_TOKEN}}\\\" },
            { key: \\\"use_auth_token\\\", value: \\\"{{PYANNOTE_AUTH_TOKEN}}\\\" }
          ],
          gpuTypeId: \\\"$GPU_TYPE\\\",
          gpuCount: $GPU_COUNT
        }
      ) {
        id
        name
        imageName
      }
    }\"
  }")

echo "  Response: $UPDATE_RESPONSE"

echo ""
echo "============================================================"
echo "Setup complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Rebuild and push your Docker image:"
echo "     docker build -t leandrodisconzi/transcription-transcription:serverless ."
echo "     docker push leandrodisconzi/transcription-transcription:serverless"
echo ""
echo "  2. Check your endpoint status at: https://www.runpod.io/console/serverless"
echo "  3. Wait for endpoint to show status: RUNNING"
echo "  4. Test with the Python client (runpod_client_example.py):"
echo ""
echo "     python runpod_client_example.py"
echo ""
echo "  Or use curl with the Runpod API:"
echo ""
echo "     curl -X POST 'https://api.runpod.ai/v2/5j22h5dqpbj6kh/runsync' \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -H 'Authorization: Bearer YOUR_API_KEY' \\"
echo "       -d '{\"input\":{\"task\":\"excerpt\",\"file_path\":\"/workspace/data/originals/file.wav\",\"start\":15,\"end\":30}}'"
echo ""
echo "============================================================"
