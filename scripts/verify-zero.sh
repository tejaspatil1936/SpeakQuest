#!/usr/bin/env bash
# Verify that nothing billable from SpeakQuest is left in the account
# (system design §8.5). Runs automatically after `make down`.
#
#   scripts/verify-zero.sh            # everything named speakquest*
#   PREFIX=speakquest-test scripts/verify-zero.sh
#
# Exit codes: 0 = verified empty, 1 = leftovers found, 3 = some checks could
# not run (e.g. denied by an organisation SCP) and nothing else was found.
# The tagging API can list just-deleted resources for a few minutes; re-run
# if something appears right after a destroy.
set -uo pipefail

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
PREFIX="${PREFIX:-speakquest}"
export AWS_PAGER=""
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"

found=0
skipped=0

check() {
  # check "<label>" <aws args...>  — prints leftovers, tracks failures.
  local label="$1"; shift
  local out err
  err="$(mktemp)"
  if out="$(aws --region "$REGION" --output text "$@" 2>"$err")"; then
    out="$(printf '%s' "$out" | tr '\t' '\n' | sed '/^None$/d;/^$/d')"
    if [[ -n "$out" ]]; then
      echo "LEFTOVER $label:"
      printf '%s\n' "$out" | sed 's/^/  /'
      found=1
    else
      echo "ok       $label"
    fi
  else
    echo "SKIPPED  $label — $(grep -oE '(AccessDenied[A-Za-z]*|UnauthorizedOperation|explicit deny[^.]*|Could not connect[^.]*)' "$err" | head -1)"
    skipped=1
  fi
  rm -f "$err"
}

echo "Region $REGION, prefix '$PREFIX'"

# Primary check from the design: anything still carrying the project tag.
check "tagged resources (project=speakquest)" resourcegroupstaggingapi get-resources \
  --tag-filters Key=project,Values=speakquest \
  --query 'ResourceTagMappingList[].ResourceARN'

# Per-service checks: they also catch untagged leftovers, and still work
# where the tagging API is denied.
check "log groups /aws/lambda" logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/$PREFIX" --query 'logGroups[].logGroupName'
check "log groups /aws/vendedlogs/states" logs describe-log-groups \
  --log-group-name-prefix "/aws/vendedlogs/states/$PREFIX" --query 'logGroups[].logGroupName'
check "log groups /aws/apigateway" logs describe-log-groups \
  --log-group-name-prefix "/aws/apigateway/$PREFIX" --query 'logGroups[].logGroupName'
check "ECR repositories" ecr describe-repositories \
  --query "repositories[?starts_with(repositoryName,'$PREFIX')].repositoryName"
check "S3 buckets" s3api list-buckets \
  --query "Buckets[?starts_with(Name,'$PREFIX')].Name"
check "DynamoDB tables" dynamodb list-tables \
  --query "TableNames[?starts_with(@,'$PREFIX')]"
check "Lambda functions" lambda list-functions \
  --query "Functions[?starts_with(FunctionName,'$PREFIX')].FunctionName"
check "state machines" stepfunctions list-state-machines \
  --query "stateMachines[?starts_with(name,'$PREFIX')].name"
check "HTTP APIs" apigatewayv2 get-apis \
  --query "Items[?starts_with(Name,'$PREFIX')].Name"
check "IAM roles" iam list-roles \
  --query "Roles[?starts_with(RoleName,'$PREFIX')].RoleName"
check "SNS topics" sns list-topics \
  --query "Topics[?contains(TopicArn,':$PREFIX')].TopicArn"
check "CloudWatch alarms" cloudwatch describe-alarms \
  --alarm-name-prefix "$PREFIX" --query 'MetricAlarms[].AlarmName'
ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
if [[ -n "$ACCOUNT" ]]; then
  check "budgets" budgets describe-budgets --account-id "$ACCOUNT" \
    --query "Budgets[?starts_with(BudgetName,'$PREFIX')].BudgetName"
fi

if (( found )); then
  echo "Leftovers found. Re-run in a few minutes if a destroy just finished."
  exit 1
fi
if (( skipped )); then
  echo "Nothing found, but some checks were not allowed to run — not verified as zero."
  exit 3
fi
echo "Done. Nothing left to bill."
