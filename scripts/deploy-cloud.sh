#!/bin/bash

# Cloud deployment script for Audio Text Backend
# Deploys API and Worker containers to Google Cloud Run

set -e

# Default configuration
PROJECT_ID=""
REGION="europe-west4"
SERVICE="all"
TAG="latest"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--project)
            PROJECT_ID="$2"
            shift 2
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -s|--service)
            SERVICE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 -p PROJECT_ID [-r REGION] [-s SERVICE]"
            echo ""
            echo "Options:"
            echo "  -p, --project   GCP project ID (required)"
            echo "  -r, --region    GCP region (default: europe-west4)"
            echo "  -s, --service   Service to deploy: api, worker, or all (default: all)"
            echo ""
            echo "Examples:"
            echo "  $0 -p my-project-id"
            echo "  $0 -p my-project-id -s api"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate project ID
if [[ -z "$PROJECT_ID" ]]; then
    echo "Error: Project ID is required (-p)"
    exit 1
fi

# Set GCP project
gcloud config set project ${PROJECT_ID}

# Image names
API_IMAGE="gcr.io/${PROJECT_ID}/audio-api:${TAG}"
WORKER_IMAGE="gcr.io/${PROJECT_ID}/audio-worker:${TAG}"

# Build and deploy API
if [[ "$SERVICE" == "api" || "$SERVICE" == "all" ]]; then
    echo "Building API image..."
    gcloud builds submit --tag ${API_IMAGE} --target api .

    echo "Deploying API to Cloud Run..."
    gcloud run deploy audio-api \
        --image ${API_IMAGE} \
        --region ${REGION} \
        --platform managed \
        --memory 1Gi \
        --cpu 1 \
        --min-instances 0 \
        --max-instances 10 \
        --allow-unauthenticated \
        --port 3203
fi

# Build and deploy Worker
if [[ "$SERVICE" == "worker" || "$SERVICE" == "all" ]]; then
    echo "Building Worker image (this may take 10-15 minutes)..."
    gcloud builds submit --tag ${WORKER_IMAGE} --target worker --timeout=1800s --machine-type=n1-highcpu-8 .

    echo "Deploying Worker to Cloud Run..."
    gcloud run deploy audio-worker \
        --image ${WORKER_IMAGE} \
        --region ${REGION} \
        --platform managed \
        --memory 4Gi \
        --cpu 2 \
        --min-instances 1 \
        --max-instances 5 \
        --no-allow-unauthenticated \
        --port 3203
fi

echo ""
echo "Deployment complete!"
echo "View services: gcloud run services list --region ${REGION}"
