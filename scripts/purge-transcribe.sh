#!/usr/bin/env bash
# Delete SpeakQuest transcription job records (they cost nothing, but keep
# the console tidy). Optional; see system design §8.6.
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
PREFIX="${PREFIX:-speakquest}"
export AWS_PAGER=""
jobs="$(aws --region "$REGION" transcribe list-transcription-jobs --job-name-contains "$PREFIX" \
  --max-results 100 --query 'TranscriptionJobSummaries[].TranscriptionJobName' --output text)"
for job in $jobs; do
  [[ "$job" == None ]] && continue
  aws --region "$REGION" transcribe delete-transcription-job --transcription-job-name "$job"
  echo "deleted $job"
done
