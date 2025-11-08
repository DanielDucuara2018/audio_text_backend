#!/bin/bash

# Cloud deployment script for Audio Text Backend
# Deploys API and Worker containers to Google Cloud Run
# Infrastructure (DB, Redis, etc.) must be created with Terraform first

set -e

# Default configuration
PROJECT_ID=""
REGION="europe-west4"
SERVICE="all"
TAG="latest"
TERRAFORM_DIR="../audio_text_infrastructure"
AUTO_FETCH_CONFIG=true

# Application configuration (matching ci/deployment.yaml defaults)
MAX_FILE_SIZE="${AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV:-100}"
ALLOWED_EXTENSIONS="${AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV:-mp3,wav,flac,mp4,m4a,aac,ogg}"
RATE_LIMIT_MINUTE="${AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV:-60}"
RATE_LIMIT_HOUR="${AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV:-1000}"
REDIS_CHANNEL="${AUDIO_TEXT_REDIS_PUB_SUB_CHANNEL_ENV:-job_updates}"
CELERY_QUEUE="${AUDIO_TEXT_CELERY_QUEUE_NAME_ENV:-audio_processing}"
CELERY_ROUTING_KEY="${AUDIO_TEXT_CELERY_ROUTING_KEY_ENV:-audio_processing}"
DB_REF_TABLE="${AUDIO_TEXT_DB_REF_TABLE_ENV:-transcription_job}"

# AWS Configuration
AWS_REGION="${AUDIO_TEXT_AWS_REGION_ENV:-eu-west-3}"

# Whisper configuration (for Worker, but API needs them in config too)
WHISPER_DEVICE="${AUDIO_TEXT_WHISPER_DEVICE_ENV:-cpu}"
WHISPER_COMPUTE_TYPE="${AUDIO_TEXT_WHISPER_COMPUTE_TYPE_ENV:-int8}"
WHISPER_CPU_THREADS="${AUDIO_TEXT_WHISPER_CPU_THREADS_ENV:-4}"
WHISPER_BEAM_SIZE="${AUDIO_TEXT_WHISPER_BEAM_SIZE_ENV:-5}"
WHISPER_WORD_TIMESTAMPS="${AUDIO_TEXT_WHISPER_WORD_TIMESTAMPS_ENV:-true}"
WHISPER_VAD_FILTER="${AUDIO_TEXT_WHISPER_VAD_FILTER_ENV:-true}"
WHISPER_VAD_MIN_SILENCE_MS="${AUDIO_TEXT_WHISPER_VAD_MIN_SILENCE_MS_ENV:-500}"

# Infrastructure variables (will be fetched from Terraform)
DB_HOST=""
DB_NAME=""
DB_USER=""
DB_PASSWORD=""
REDIS_HOST=""
REDIS_PORT=""
BUCKET_NAME=""
VPC_CONNECTOR=""
CORS_ORIGINS=""
API_CPU="1"
API_MEMORY="1Gi"
API_MIN_INSTANCES="0"
API_MAX_INSTANCES="10"
WORKER_CPU="2"
WORKER_MEMORY="2Gi"
WORKER_MIN_INSTANCES="1"
WORKER_MAX_INSTANCES="5"

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
        -t|--terraform-dir)
            TERRAFORM_DIR="$2"
            shift 2
            ;;
        --no-auto-fetch)
            AUTO_FETCH_CONFIG=false
            shift
            ;;
        -h|--help)
            echo "Usage: $0 -p PROJECT_ID [-r REGION] [-s SERVICE] [-t TERRAFORM_DIR]"
            echo ""
            echo "Options:"
            echo "  -p, --project      GCP project ID (required)"
            echo "  -r, --region       GCP region (default: europe-west4)"
            echo "  -s, --service      Service to deploy: api, worker, or all (default: all)"
            echo "  -t, --terraform-dir Path to Terraform directory (default: ../audio_text_infrastructure)"
            echo "  --no-auto-fetch    Don't automatically fetch config from Terraform"
            echo ""
            echo "Examples:"
            echo "  $0 -p my-project-id"
            echo "  $0 -p my-project-id -s api"
            echo "  $0 -p my-project-id -t /path/to/terraform"
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

# Fetch infrastructure configuration from Terraform outputs
if [[ "$AUTO_FETCH_CONFIG" == "true" ]]; then
    echo "Fetching infrastructure configuration from Terraform..."

    if [[ ! -d "$TERRAFORM_DIR" ]]; then
        echo "Warning: Terraform directory not found at $TERRAFORM_DIR"
        echo "Make sure to run 'terraform apply' first, or provide custom config"
    else
        cd "$TERRAFORM_DIR"

        # Check if terraform state exists
        if terraform show &> /dev/null; then
            # Extract deployment config from Terraform outputs
            DEPLOY_CONFIG=$(terraform output -json deployment_config 2>/dev/null | jq -r '.')

            if [[ -n "$DEPLOY_CONFIG" && "$DEPLOY_CONFIG" != "null" ]]; then
                DB_HOST=$(echo "$DEPLOY_CONFIG" | jq -r '.db_host')
                DB_NAME=$(echo "$DEPLOY_CONFIG" | jq -r '.db_name')
                DB_USER=$(echo "$DEPLOY_CONFIG" | jq -r '.db_user')
                REDIS_HOST=$(echo "$DEPLOY_CONFIG" | jq -r '.redis_host')
                REDIS_PORT=$(echo "$DEPLOY_CONFIG" | jq -r '.redis_port')
                BUCKET_NAME=$(echo "$DEPLOY_CONFIG" | jq -r '.bucket_name')
                VPC_CONNECTOR=$(echo "$DEPLOY_CONFIG" | jq -r '.vpc_connector')
                CORS_ORIGINS=$(echo "$DEPLOY_CONFIG" | jq -r '.cors_origins')
                API_CPU=$(echo "$DEPLOY_CONFIG" | jq -r '.api_cpu')
                API_MEMORY=$(echo "$DEPLOY_CONFIG" | jq -r '.api_memory')
                API_MIN_INSTANCES=$(echo "$DEPLOY_CONFIG" | jq -r '.api_min_instances')
                API_MAX_INSTANCES=$(echo "$DEPLOY_CONFIG" | jq -r '.api_max_instances')
                WORKER_CPU=$(echo "$DEPLOY_CONFIG" | jq -r '.worker_cpu')
                WORKER_MEMORY=$(echo "$DEPLOY_CONFIG" | jq -r '.worker_memory')
                WORKER_MIN_INSTANCES=$(echo "$DEPLOY_CONFIG" | jq -r '.worker_min_instances')
                WORKER_MAX_INSTANCES=$(echo "$DEPLOY_CONFIG" | jq -r '.worker_max_instances')

                # Get sensitive values
                DB_PASSWORD=$(terraform output -raw database_password 2>/dev/null)

                echo "✅ Configuration loaded from Terraform"
            else
                echo "⚠️  Warning: Could not read deployment_config output from Terraform"
                echo "    Make sure you've run 'terraform apply' first"
            fi
        else
            echo "⚠️  Warning: No Terraform state found in $TERRAFORM_DIR"
            echo "    Please run 'terraform apply' first to create infrastructure"
            exit 1
        fi

        cd - > /dev/null
    fi
fi

# Image names
API_IMAGE="gcr.io/${PROJECT_ID}/audio-api:${TAG}"
WORKER_IMAGE="gcr.io/${PROJECT_ID}/audio-worker:${TAG}"

# Build and deploy API
if [[ "$SERVICE" == "api" || "$SERVICE" == "all" ]]; then
    echo ""
    echo "======================================"
    echo "Building and Deploying API Service"
    echo "======================================"
    echo "Building API image locally..."
    docker build --target api -t ${API_IMAGE} .

    echo "Pushing API image to GCR..."
    docker push ${API_IMAGE}

    echo "Deploying API to Cloud Run..."
    gcloud run deploy audio-api \
        --image ${API_IMAGE} \
        --region ${REGION} \
        --platform managed \
        --memory ${API_MEMORY} \
        --cpu ${API_CPU} \
        --min-instances ${API_MIN_INSTANCES} \
        --max-instances ${API_MAX_INSTANCES} \
        --allow-unauthenticated \
        --port 3203 \
        --vpc-connector ${VPC_CONNECTOR} \
        --vpc-egress private-ranges-only \
        --set-env-vars "AUDIO_TEXT_DB_HOST_ENV=${DB_HOST}" \
        --set-env-vars "AUDIO_TEXT_DB_NAME_ENV=${DB_NAME}" \
        --set-env-vars "AUDIO_TEXT_DB_USER_ENV=${DB_USER}" \
        --set-env-vars "AUDIO_TEXT_DB_PASSWORD_ENV=${DB_PASSWORD}" \
        --set-env-vars "AUDIO_TEXT_DB_PORT_ENV=5432" \
        --set-env-vars "AUDIO_TEXT_REDIS_HOST_ENV=${REDIS_HOST}" \
        --set-env-vars "AUDIO_TEXT_REDIS_PORT_ENV=${REDIS_PORT}" \
        --set-env-vars "AUDIO_TEXT_AWS_BUCKET_NAME_ENV=${BUCKET_NAME}" \
        --set-env-vars "AUDIO_TEXT_AWS_REGION_ENV=${AWS_REGION}" \
        --set-env-vars "AUDIO_TEXT_CORS_ORIGINS_ENV=${CORS_ORIGINS}" \
        --set-env-vars "AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV=${MAX_FILE_SIZE}" \
        --set-env-vars "^@^AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV=${ALLOWED_EXTENSIONS}" \
        --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV=${RATE_LIMIT_MINUTE}" \
        --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV=${RATE_LIMIT_HOUR}" \
        --set-env-vars "AUDIO_TEXT_REDIS_PUB_SUB_CHANNEL_ENV=${REDIS_CHANNEL}" \
        --set-env-vars "AUDIO_TEXT_CELERY_QUEUE_NAME_ENV=${CELERY_QUEUE}" \
        --set-env-vars "AUDIO_TEXT_CELERY_ROUTING_KEY_ENV=${CELERY_ROUTING_KEY}" \
        --set-env-vars "AUDIO_TEXT_DB_REF_TABLE_ENV=${DB_REF_TABLE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_DEVICE_ENV=${WHISPER_DEVICE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_COMPUTE_TYPE_ENV=${WHISPER_COMPUTE_TYPE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_CPU_THREADS_ENV=${WHISPER_CPU_THREADS}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_BEAM_SIZE_ENV=${WHISPER_BEAM_SIZE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_WORD_TIMESTAMPS_ENV=${WHISPER_WORD_TIMESTAMPS}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_VAD_FILTER_ENV=${WHISPER_VAD_FILTER}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_VAD_MIN_SILENCE_MS_ENV=${WHISPER_VAD_MIN_SILENCE_MS}" \
        --update-secrets "AUDIO_TEXT_AWS_ACCESS_KEY_ENV=audio-text-aws-access-key:latest,AUDIO_TEXT_AWS_SECRET_KEY_ENV=audio-text-aws-secret-key:latest"

    echo "✅ API service deployed successfully"
fi

# Build and deploy Worker
if [[ "$SERVICE" == "worker" || "$SERVICE" == "all" ]]; then
    echo ""
    echo "======================================"
    echo "Building and Deploying Worker Service"
    echo "======================================"
    echo "Building Worker image (this may take 10-15 minutes)..."
    docker build --target worker -t ${WORKER_IMAGE} .

    echo "Pushing Worker image to GCR..."
    docker push ${WORKER_IMAGE}

    echo "Deploying Worker to Cloud Run..."
    gcloud run deploy audio-worker \
        --image ${WORKER_IMAGE} \
        --region ${REGION} \
        --platform managed \
        --memory ${WORKER_MEMORY} \
        --cpu ${WORKER_CPU} \
        --min-instances ${WORKER_MIN_INSTANCES} \
        --max-instances ${WORKER_MAX_INSTANCES} \
        --no-allow-unauthenticated \
        --no-cpu-throttling \
        --port 8080 \
        --vpc-connector ${VPC_CONNECTOR} \
        --vpc-egress private-ranges-only \
        --set-env-vars "AUDIO_TEXT_DB_HOST_ENV=${DB_HOST}" \
        --set-env-vars "AUDIO_TEXT_DB_NAME_ENV=${DB_NAME}" \
        --set-env-vars "AUDIO_TEXT_DB_USER_ENV=${DB_USER}" \
        --set-env-vars "AUDIO_TEXT_DB_PASSWORD_ENV=${DB_PASSWORD}" \
        --set-env-vars "AUDIO_TEXT_DB_PORT_ENV=5432" \
        --set-env-vars "AUDIO_TEXT_REDIS_HOST_ENV=${REDIS_HOST}" \
        --set-env-vars "AUDIO_TEXT_REDIS_PORT_ENV=${REDIS_PORT}" \
        --set-env-vars "AUDIO_TEXT_AWS_BUCKET_NAME_ENV=${BUCKET_NAME}" \
        --set-env-vars "AUDIO_TEXT_AWS_REGION_ENV=${AWS_REGION}" \
        --set-env-vars "AUDIO_TEXT_CORS_ORIGINS_ENV=${CORS_ORIGINS}" \
        --set-env-vars "AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV=${MAX_FILE_SIZE}" \
        --set-env-vars "^@^AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV=${ALLOWED_EXTENSIONS}" \
        --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV=${RATE_LIMIT_MINUTE}" \
        --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV=${RATE_LIMIT_HOUR}" \
        --set-env-vars "AUDIO_TEXT_REDIS_PUB_SUB_CHANNEL_ENV=${REDIS_CHANNEL}" \
        --set-env-vars "AUDIO_TEXT_CELERY_QUEUE_NAME_ENV=${CELERY_QUEUE}" \
        --set-env-vars "AUDIO_TEXT_CELERY_ROUTING_KEY_ENV=${CELERY_ROUTING_KEY}" \
        --set-env-vars "AUDIO_TEXT_DB_REF_TABLE_ENV=${DB_REF_TABLE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_DEVICE_ENV=${WHISPER_DEVICE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_COMPUTE_TYPE_ENV=${WHISPER_COMPUTE_TYPE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_CPU_THREADS_ENV=${WHISPER_CPU_THREADS}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_BEAM_SIZE_ENV=${WHISPER_BEAM_SIZE}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_WORD_TIMESTAMPS_ENV=${WHISPER_WORD_TIMESTAMPS}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_VAD_FILTER_ENV=${WHISPER_VAD_FILTER}" \
        --set-env-vars "AUDIO_TEXT_WHISPER_VAD_MIN_SILENCE_MS_ENV=${WHISPER_VAD_MIN_SILENCE_MS}" \
        --update-secrets "AUDIO_TEXT_AWS_ACCESS_KEY_ENV=audio-text-aws-access-key:latest,AUDIO_TEXT_AWS_SECRET_KEY_ENV=audio-text-aws-secret-key:latest"

    echo "✅ Worker service deployed successfully"
fi

echo ""
echo "======================================"
echo "Deployment Complete!"
echo "======================================"
echo "View services: gcloud run services list --region ${REGION}"
echo ""
echo "API URL: https://audio-api-<hash>-${REGION}.run.app"
echo "Worker URL: https://audio-worker-<hash>-${REGION}.run.app (internal only)"
