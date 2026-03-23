#!/bin/bash
# One-time IAM setup for the Audio Worker Cloud Run Jobs service account.
#
# Run this once per GCP project before the first worker deployment, or
# whenever the project's IAM configuration needs to be restored.
#
# Required roles granted to audio-worker-sa:
#   roles/run.invoker              — lets Pub/Sub trigger Cloud Run Job executions
#   roles/pubsub.subscriber        — lets the job container pull messages from subscriptions
#   roles/secretmanager.secretAccessor — lets the job container read Secret Manager secrets
#   roles/iam.serviceAccountTokenCreator (on the SA itself, granted to the Pub/Sub agent)
#                                  — lets Pub/Sub mint OIDC tokens for push auth

set -e

PROJECT_ID=""
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--project) PROJECT_ID="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 -p PROJECT_ID"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

[[ -z "$PROJECT_ID" ]] && { echo "Error: -p PROJECT_ID is required"; exit 1; }

CRJ_SA="audio-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Setting up IAM for ${CRJ_SA} in project ${PROJECT_ID} ==="

if ! gcloud iam service-accounts describe "${CRJ_SA}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "Creating service account ${CRJ_SA}..."
    gcloud iam service-accounts create audio-worker-sa \
        --display-name="Audio Worker Cloud Run Jobs SA" \
        --project="${PROJECT_ID}"
fi

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CRJ_SA}" \
    --role="roles/run.invoker" \
    --condition=None \
    --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CRJ_SA}" \
    --role="roles/pubsub.subscriber" \
    --condition=None \
    --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CRJ_SA}" \
    --role="roles/pubsub.publisher" \
    --condition=None \
    --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CRJ_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None \
    --quiet

PUBSUB_SA="service-$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')@gcp-sa-pubsub.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "${CRJ_SA}" \
    --member="serviceAccount:${PUBSUB_SA}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project="${PROJECT_ID}" \
    --quiet

echo "IAM setup complete for ${CRJ_SA}."
