#!/bin/bash
# Cloud deployment script for Audio Text Backend.
#
# Architecture (Cloud Run Jobs + Pub/Sub):
#   audio-api                         — Cloud Run Service  (receives requests, pushes to Pub/Sub)
#   audio-worker-{small,medium,large} — Cloud Run Jobs (one invocation per transcription job)
#
# Pub/Sub resources (managed by Terraform / gcloud):
#   transcription-jobs topic  — API publishes here; model_tier attribute routes to tier CRJ
#     └ transcription-jobs-sub-{small,medium,large}  — filtered push subs trigger per-tier CRJ
#   transcription-status topic — worker publishes status updates here
#     └ transcription-status-push — push subscription → API /pubsub/status
#
# Prerequisites:
#   1. Run Terraform to create VPC, Cloud SQL, and GCS bucket.
#   2. Create GCP Secret Manager secrets (see --help for names).
#   3. Ensure the Cloud Run service account has the required IAM roles.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
"$SCRIPT_DIR/populate-env-variables.sh"

# ── defaults ──────────────────────────────────────────────────────────────────
REGION="europe-west4"
SERVICE="all"
TAG="latest"
TERRAFORM_DIR="../audio_text_infrastructure"
AUTO_FETCH_CONFIG=true

# Application
MAX_FILE_SIZE="${AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV:-100}"
ALLOWED_EXTENSIONS="${AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV:-mp3,wav,flac,mp4,m4a,aac,ogg,opus}"
RATE_LIMIT_MINUTE="${AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV:-60}"
RATE_LIMIT_HOUR="${AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV:-1000}"
DB_REF_TABLE="${AUDIO_TEXT_DB_REF_TABLE_ENV:-transcription_job}"

# Whisper
WHISPER_DEVICE="${AUDIO_TEXT_WHISPER_DEVICE_ENV:-cpu}"
WHISPER_COMPUTE_TYPE="${AUDIO_TEXT_WHISPER_COMPUTE_TYPE_ENV:-int8}"
WHISPER_CPU_THREADS="${AUDIO_TEXT_WHISPER_CPU_THREADS_ENV:-4}"
WHISPER_BEAM_SIZE="${AUDIO_TEXT_WHISPER_BEAM_SIZE_ENV:-5}"
WHISPER_VAD_FILTER="${AUDIO_TEXT_WHISPER_VAD_FILTER_ENV:-true}"
WHISPER_VAD_MIN_SILENCE_MS="${AUDIO_TEXT_WHISPER_VAD_MIN_SILENCE_MS_ENV:-500}"

# Email
EMAIL_FROM="${AUDIO_TEXT_EMAIL_FROM_ENV:-noreply@voiceia.danobhub.com}"
EMAIL_FROM_NAME="${AUDIO_TEXT_EMAIL_FROM_NAME_ENV:-VoiceIA}"

# AWS
AWS_REGION="${AUDIO_TEXT_AWS_REGION_ENV:-eu-west-3}"

# Infrastructure (filled from Terraform or overridden)
DB_HOST=""
DB_NAME=""
DB_USER=""
DB_PASSWORD=""
BUCKET_NAME=""
VPC_CONNECTOR=""
CORS_ORIGINS=""
PUBSUB_PROJECT_ID=""
PUBSUB_JOBS_TOPIC=""
PUBSUB_STATUS_TOPIC=""
PUBSUB_JOBS_SUB_SMALL=""
PUBSUB_JOBS_SUB_MEDIUM=""
PUBSUB_JOBS_SUB_LARGE=""
PUBSUB_STATUS_SUB=""
API_URL=""  # Load Balancer URL (https://api_subdomain) — sourced from Terraform
API_CPU="1"
API_MEMORY="1Gi"
API_MIN_INSTANCES="0"
API_MAX_INSTANCES="10"
WORKER_SMALL_CPU="2"
WORKER_SMALL_MEMORY="2Gi"
WORKER_MEDIUM_CPU="4"
WORKER_MEDIUM_MEMORY="8Gi"
WORKER_LARGE_CPU="6"
WORKER_LARGE_MEMORY="16Gi"

# ── argument parsing ───────────────────────────────────────────────────────────
PROJECT_ID=""
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--project)      PROJECT_ID="$2"; shift 2 ;;
        -r|--region)       REGION="$2"; shift 2 ;;
        -s|--service)      SERVICE="$2"; shift 2 ;;  # api | worker | all
        -t|--terraform-dir) TERRAFORM_DIR="$2"; shift 2 ;;
        --no-auto-fetch)   AUTO_FETCH_CONFIG=false; shift ;;
        -h|--help)
            echo "Usage: $0 -p PROJECT_ID [-r REGION] [-s SERVICE] [-t TERRAFORM_DIR]"
            echo ""
            echo "  -s SERVICE   api | worker | all  (default: all)"
            echo ""
            echo "Required Secret Manager secrets:"
            echo "  audio-text-db-password"
            echo "  audio-text-aws-access-key"
            echo "  audio-text-aws-secret-key"
            echo "  audio-text-sendgrid-api-key"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

[[ -z "$PROJECT_ID" ]] && { echo "Error: -p PROJECT_ID is required"; exit 1; }
PUBSUB_PROJECT_ID="$PROJECT_ID"

gcloud config set project "${PROJECT_ID}"

# ── load Terraform outputs ─────────────────────────────────────────────────────
if [[ "$AUTO_FETCH_CONFIG" == "true" && -d "$TERRAFORM_DIR" ]]; then
    echo "Fetching infrastructure configuration from Terraform..."
    cd "$TERRAFORM_DIR"
    if terraform show &>/dev/null; then
        DEPLOY_CONFIG=$(terraform output -json deployment_config 2>/dev/null | jq -r '.')
        if [[ -n "$DEPLOY_CONFIG" && "$DEPLOY_CONFIG" != "null" ]]; then
            DB_HOST=$(echo "$DEPLOY_CONFIG"    | jq -r '.db_host')
            DB_NAME=$(echo "$DEPLOY_CONFIG"    | jq -r '.db_name')
            DB_USER=$(echo "$DEPLOY_CONFIG"    | jq -r '.db_user')
            BUCKET_NAME=$(echo "$DEPLOY_CONFIG" | jq -r '.bucket_name')
            VPC_CONNECTOR=$(echo "$DEPLOY_CONFIG" | jq -r '.vpc_connector')
            CORS_ORIGINS=$(echo "$DEPLOY_CONFIG" | jq -r '.cors_origins')
            PUBSUB_JOBS_TOPIC=$(echo "$DEPLOY_CONFIG"      | jq -r '.pubsub_jobs_topic')
            PUBSUB_STATUS_TOPIC=$(echo "$DEPLOY_CONFIG"    | jq -r '.pubsub_status_topic')
            PUBSUB_JOBS_SUB_SMALL=$(echo "$DEPLOY_CONFIG"  | jq -r '.pubsub_jobs_sub_small')
            PUBSUB_JOBS_SUB_MEDIUM=$(echo "$DEPLOY_CONFIG" | jq -r '.pubsub_jobs_sub_medium')
            PUBSUB_JOBS_SUB_LARGE=$(echo "$DEPLOY_CONFIG"  | jq -r '.pubsub_jobs_sub_large')
            PUBSUB_STATUS_SUB=$(echo "$DEPLOY_CONFIG"      | jq -r '.pubsub_status_subscription')
            API_URL=$(echo "$DEPLOY_CONFIG"               | jq -r '.api_url')
            DB_PASSWORD=$(terraform output -raw database_password 2>/dev/null)
            echo "Configuration loaded from Terraform."
        else
            echo "Error: Could not read deployment_config from Terraform output."
            echo "Ensure 'terraform apply' has been run and the state is available."
            exit 1
        fi
    else
        echo "Error: No Terraform state found. Run 'terraform apply' first."
        exit 1
    fi
    cd - >/dev/null
fi

# Validate that all variables sourced from Terraform are present.
# Every variable initialized to "" above must be non-empty before deployment proceeds.
missing_vars=()
# Database
[[ -z "$DB_HOST" ]]               && missing_vars+=("DB_HOST")
[[ -z "$DB_NAME" ]]               && missing_vars+=("DB_NAME")
[[ -z "$DB_USER" ]]               && missing_vars+=("DB_USER")
[[ -z "$DB_PASSWORD" ]]           && missing_vars+=("DB_PASSWORD")
# Storage / networking
[[ -z "$BUCKET_NAME" ]]           && missing_vars+=("BUCKET_NAME")
[[ -z "$VPC_CONNECTOR" ]]         && missing_vars+=("VPC_CONNECTOR")
[[ -z "$CORS_ORIGINS" ]]          && missing_vars+=("CORS_ORIGINS")
# Pub/Sub
[[ -z "$PUBSUB_JOBS_TOPIC" ]]     && missing_vars+=("PUBSUB_JOBS_TOPIC")
[[ -z "$PUBSUB_STATUS_TOPIC" ]]   && missing_vars+=("PUBSUB_STATUS_TOPIC")
[[ -z "$PUBSUB_JOBS_SUB_SMALL" ]] && missing_vars+=("PUBSUB_JOBS_SUB_SMALL")
[[ -z "$PUBSUB_JOBS_SUB_MEDIUM" ]] && missing_vars+=("PUBSUB_JOBS_SUB_MEDIUM")
[[ -z "$PUBSUB_JOBS_SUB_LARGE" ]] && missing_vars+=("PUBSUB_JOBS_SUB_LARGE")
[[ -z "$PUBSUB_STATUS_SUB" ]]     && missing_vars+=("PUBSUB_STATUS_SUB")
# API endpoint (Load Balancer URL — must NOT come from gcloud run services describe)
[[ -z "$API_URL" ]]               && missing_vars+=("API_URL")
if [[ ${#missing_vars[@]} -gt 0 ]]; then
    echo "Error: The following variables could not be loaded from Terraform:"
    printf '  %s\n' "${missing_vars[@]}"
    echo "Run 'terraform apply' in ${TERRAFORM_DIR} and retry, or use --no-auto-fetch to skip."
    exit 1
fi

# Shared env-var flags used by both API and worker
COMMON_DB_VARS=(
    --set-env-vars "AUDIO_TEXT_DB_HOST_ENV=${DB_HOST}"
    --set-env-vars "AUDIO_TEXT_DB_NAME_ENV=${DB_NAME}"
    --set-env-vars "AUDIO_TEXT_DB_USER_ENV=${DB_USER}"
    --set-env-vars "AUDIO_TEXT_DB_PORT_ENV=5432"
    --set-env-vars "AUDIO_TEXT_DB_REF_TABLE_ENV=${DB_REF_TABLE}"
    --set-env-vars "AUDIO_TEXT_DB_SKIP_MIGRATION_ENV=false"
    --set-env-vars "AUDIO_TEXT_AWS_BUCKET_NAME_ENV=${BUCKET_NAME}"
    --set-env-vars "AUDIO_TEXT_AWS_REGION_ENV=${AWS_REGION}"
    --set-env-vars "AUDIO_TEXT_PUBSUB_PROJECT_ID_ENV=${PUBSUB_PROJECT_ID}"
    --set-env-vars "AUDIO_TEXT_PUBSUB_JOBS_TOPIC_ENV=${PUBSUB_JOBS_TOPIC}"
    --set-env-vars "AUDIO_TEXT_PUBSUB_STATUS_TOPIC_ENV=${PUBSUB_STATUS_TOPIC}"
    --set-env-vars "AUDIO_TEXT_PUBSUB_JOBS_SUBSCRIPTION_ENV=${PUBSUB_JOBS_TOPIC}-sub"
    --set-env-vars "AUDIO_TEXT_PUBSUB_STATUS_SUBSCRIPTION_ENV=${PUBSUB_STATUS_SUB}"
    --set-env-vars "AUDIO_TEXT_PUBSUB_JOBS_SUB_SMALL_ENV=${PUBSUB_JOBS_SUB_SMALL}"
    --set-env-vars "AUDIO_TEXT_PUBSUB_JOBS_SUB_MEDIUM_ENV=${PUBSUB_JOBS_SUB_MEDIUM}"
    --set-env-vars "AUDIO_TEXT_PUBSUB_JOBS_SUB_LARGE_ENV=${PUBSUB_JOBS_SUB_LARGE}"
    --set-env-vars "AUDIO_TEXT_WHISPER_DEVICE_ENV=${WHISPER_DEVICE}"
    --set-env-vars "AUDIO_TEXT_WHISPER_COMPUTE_TYPE_ENV=${WHISPER_COMPUTE_TYPE}"
    --set-env-vars "AUDIO_TEXT_WHISPER_CPU_THREADS_ENV=${WHISPER_CPU_THREADS}"
    --set-env-vars "AUDIO_TEXT_WHISPER_BEAM_SIZE_ENV=${WHISPER_BEAM_SIZE}"
    --set-env-vars "AUDIO_TEXT_WHISPER_VAD_FILTER_ENV=${WHISPER_VAD_FILTER}"
    --set-env-vars "AUDIO_TEXT_WHISPER_VAD_MIN_SILENCE_MS_ENV=${WHISPER_VAD_MIN_SILENCE_MS}"
    --set-env-vars "AUDIO_TEXT_EMAIL_FROM_ENV=${EMAIL_FROM}"
    --set-env-vars "AUDIO_TEXT_EMAIL_FROM_NAME_ENV=${EMAIL_FROM_NAME}"
    --set-secrets "AUDIO_TEXT_DB_PASSWORD_ENV=audio-text-db-password:latest,AUDIO_TEXT_AWS_ACCESS_KEY_ENV=audio-text-aws-access-key:latest,AUDIO_TEXT_AWS_SECRET_KEY_ENV=audio-text-aws-secret-key:latest,AUDIO_TEXT_SENDGRID_API_KEY_ENV=audio-text-sendgrid-api-key:latest"
)

API_IMAGE="gcr.io/${PROJECT_ID}/audio-api:${TAG}"
WORKER_IMAGE="gcr.io/${PROJECT_ID}/audio-worker:${TAG}"

# ── deploy API ─────────────────────────────────────────────────────────────────
if [[ "$SERVICE" == "api" || "$SERVICE" == "all" ]]; then
    echo ""
    echo "=== Building and deploying API ==="
    docker build --target api -t "${API_IMAGE}" --no-cache .
    docker push "${API_IMAGE}"

    gcloud run deploy audio-api \
        --image "${API_IMAGE}" \
        --region "${REGION}" \
        --platform managed \
        --memory "${API_MEMORY}" \
        --cpu "${API_CPU}" \
        --min-instances "${API_MIN_INSTANCES}" \
        --max-instances "${API_MAX_INSTANCES}" \
        --allow-unauthenticated \
        --ingress internal-and-cloud-load-balancing \
        --port 3203 \
        --timeout=60 \
        --vpc-connector "${VPC_CONNECTOR}" \
        --vpc-egress private-ranges-only \
        --session-affinity \
        --set-env-vars "AUDIO_TEXT_WORKER_TIER_ENV=" \
        --set-env-vars "AUDIO_TEXT_CORS_ORIGINS_ENV=${CORS_ORIGINS}" \
        --set-env-vars "AUDIO_TEXT_PUBSUB_API_PUSH_ENDPOINT_ENV=${API_URL}/api/v1/pubsub/status" \
        --set-env-vars "AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV=${MAX_FILE_SIZE}" \
        --set-env-vars "^@^AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV=${ALLOWED_EXTENSIONS}" \
        --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV=${RATE_LIMIT_MINUTE}" \
        --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV=${RATE_LIMIT_HOUR}" \
        "${COMMON_DB_VARS[@]}"

    echo "API deployed."

    # Configure the Pub/Sub push subscription to forward status updates to the API.
    # API_URL comes from Terraform (api_subdomain via Load Balancer) — NOT from
    # 'gcloud run services describe', which returns the internal .run.app URL that
    # is unreachable from Pub/Sub when ingress is set to internal-and-cloud-load-balancing.
    PUSH_ENDPOINT="${API_URL}/api/v1/pubsub/status"
    PUSH_SUB="transcription-status-push"

    echo "Configuring Pub/Sub push subscription -> ${PUSH_ENDPOINT}"
    gcloud pubsub subscriptions describe "${PUSH_SUB}" --project="${PUBSUB_PROJECT_ID}" &>/dev/null \
        && gcloud pubsub subscriptions modify-push-config "${PUSH_SUB}" \
               --push-endpoint="${PUSH_ENDPOINT}" \
               --project="${PUBSUB_PROJECT_ID}" \
        || gcloud pubsub subscriptions create "${PUSH_SUB}" \
               --topic="${PUBSUB_STATUS_TOPIC}" \
               --push-endpoint="${PUSH_ENDPOINT}" \
               --project="${PUBSUB_PROJECT_ID}"
    echo "Push subscription configured."
fi

# ── deploy Workers (three Cloud Run Jobs, one per model tier) ─────────────────
if [[ "$SERVICE" == "worker" || "$SERVICE" == "all" ]]; then
    echo ""
    echo "=== Building and deploying Workers (Cloud Run Jobs per model tier) ==="
    docker build --target worker -t "${WORKER_IMAGE}" --no-cache .
    docker push "${WORKER_IMAGE}"

    # Service account created and IAM roles granted by scripts/setup-worker-iam.sh.
    CRJ_SA="audio-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com"

    deploy_worker_tier() {
        local tier="$1" cpu="$2" memory="$3" sub="$4"
        local job_name="audio-worker-${tier}"
        local crj_endpoint="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${job_name}:run"

        echo "Deploying ${job_name} (cpu=${cpu}, memory=${memory})..."
        gcloud run jobs deploy "${job_name}" \
            --image "${WORKER_IMAGE}" \
            --region "${REGION}" \
            --cpu "${cpu}" \
            --memory "${memory}" \
            --max-retries 3 \
            --task-timeout 900 \
            --service-account "${CRJ_SA}" \
            --vpc-connector "${VPC_CONNECTOR}" \
            --vpc-egress private-ranges-only \
            --set-env-vars "AUDIO_TEXT_WORKER_TIER_ENV=${tier}" \
            --set-env-vars "AUDIO_TEXT_CORS_ORIGINS_ENV=${CORS_ORIGINS}" \
            --set-env-vars "AUDIO_TEXT_PUBSUB_API_PUSH_ENDPOINT_ENV=${API_URL}/api/v1/pubsub/status" \
            --set-env-vars "AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV=${MAX_FILE_SIZE}" \
            --set-env-vars "^@^AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV=${ALLOWED_EXTENSIONS}" \
            --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV=${RATE_LIMIT_MINUTE}" \
            --set-env-vars "AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV=${RATE_LIMIT_HOUR}" \
            "${COMMON_DB_VARS[@]}"

        # A separate push subscription (${sub}-push) is used solely to trigger the CRJ
        # execution when a new job message arrives on the topic.
        local push_sub="${sub}-push"
        echo "Configuring Pub/Sub push trigger '${push_sub}' -> ${job_name} (filter: model_tier=${tier})"
        if gcloud pubsub subscriptions describe "${push_sub}" --project="${PUBSUB_PROJECT_ID}" &>/dev/null; then
            gcloud pubsub subscriptions delete "${push_sub}" --project="${PUBSUB_PROJECT_ID}" --quiet
        fi
        gcloud pubsub subscriptions create "${push_sub}" \
            --topic="${PUBSUB_JOBS_TOPIC}" \
            --message-filter="attributes.model_tier = \"${tier}\"" \
            --push-endpoint="${crj_endpoint}" \
            --push-auth-service-account="${CRJ_SA}" \
            --project="${PUBSUB_PROJECT_ID}"
        echo "Push trigger configured: ${push_sub}"
    }

    deploy_worker_tier "small"  "${WORKER_SMALL_CPU}"  "${WORKER_SMALL_MEMORY}" "${PUBSUB_JOBS_SUB_SMALL}"
    deploy_worker_tier "medium" "${WORKER_MEDIUM_CPU}" "${WORKER_MEDIUM_MEMORY}" "${PUBSUB_JOBS_SUB_MEDIUM}"
    deploy_worker_tier "large"  "${WORKER_LARGE_CPU}"  "${WORKER_LARGE_MEMORY}" "${PUBSUB_JOBS_SUB_LARGE}"

    echo "All worker tiers deployed."
fi

echo ""
echo "=== Deployment complete ==="
echo "API:    https://api.voiceia.danobhub.com  (via Load Balancer)"
echo "Workers: Cloud Run Jobs audio-worker-{small,medium,large} triggered by Pub/Sub"
