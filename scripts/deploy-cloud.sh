#!/bin/bash

# Cloud deployment script for Audio Text Backend
# Deploys API and Worker containers to Google Cloud Run

set -e

# Default configuration
PROJECT_ID=""
REGION="europe-west4"
SERVICE="all"
TAG="latest"

# Application configuration (matching ci/deployment.yaml defaults)
MAX_FILE_SIZE="${AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV:-100}"
ALLOWED_EXTENSIONS="${AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV:-mp3,wav,flac,mp4,m4a,aac,ogg}"
RATE_LIMIT_MINUTE="${AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV:-60}"
RATE_LIMIT_HOUR="${AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV:-1000}"
REDIS_CHANNEL="${AUDIO_TEXT_REDIS_PUB_SUB_CHANNEL_ENV:-job_updates}"
CELERY_QUEUE="${AUDIO_TEXT_CELERY_QUEUE_NAME_ENV:-audio_processing}"
CELERY_ROUTING_KEY="${AUDIO_TEXT_CELERY_ROUTING_KEY_ENV:-audio_processing}"
DB_REF_TABLE="${AUDIO_TEXT_DB_REF_TABLE_ENV:-transcription_job}"

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
        --port 3203 \
        --set-env-vars "AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV=${MAX_FILE_SIZE},AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV=${ALLOWED_EXTENSIONS},AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV=${RATE_LIMIT_MINUTE},AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV=${RATE_LIMIT_HOUR},AUDIO_TEXT_REDIS_PUB_SUB_CHANNEL_ENV=${REDIS_CHANNEL},AUDIO_TEXT_CELERY_QUEUE_NAME_ENV=${CELERY_QUEUE},AUDIO_TEXT_CELERY_ROUTING_KEY_ENV=${CELERY_ROUTING_KEY},AUDIO_TEXT_DB_REF_TABLE_ENV=${DB_REF_TABLE}" \
        --update-secrets "AUDIO_TEXT_AWS_ACCESS_KEY_ENV=audio-text-aws-access-key:latest,AUDIO_TEXT_AWS_SECRET_KEY_ENV=audio-text-aws-secret-key:latest"
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
        --no-cpu-throttling \
        --port 3203 \
        --set-env-vars "AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV=${MAX_FILE_SIZE},AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV=${ALLOWED_EXTENSIONS},AUDIO_TEXT_REDIS_PUB_SUB_CHANNEL_ENV=${REDIS_CHANNEL},AUDIO_TEXT_CELERY_QUEUE_NAME_ENV=${CELERY_QUEUE},AUDIO_TEXT_CELERY_ROUTING_KEY_ENV=${CELERY_ROUTING_KEY},AUDIO_TEXT_DB_REF_TABLE_ENV=${DB_REF_TABLE}" \
        --update-secrets "AUDIO_TEXT_AWS_ACCESS_KEY_ENV=audio-text-aws-access-key:latest,AUDIO_TEXT_AWS_SECRET_KEY_ENV=audio-text-aws-secret-key:latest"
fi

echo ""
echo "Deployment complete!"
echo "View services: gcloud run services list --region ${REGION}"
