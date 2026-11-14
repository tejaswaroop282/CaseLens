#!/usr/bin/env bash
# Run in AWS CloudShell (Mumbai, signed in as your console user). Usage:
#   bash setup_aws_cloudshell.sh <LLM_MODEL_ID>
# Step 0 (run first, no args): lists the models your account can use in ap-south-1.
set -euo pipefail
R=ap-south-1
if [ $# -lt 1 ]; then
  aws bedrock list-foundation-models --region $R --query "modelSummaries[].modelId" --output text | tr '\t' '\n' | sort
  echo; echo "Re-run with the chosen chat model id:  bash setup_aws_cloudshell.sh <model-id>"; exit 0
fi
LLM="$1"; EMB="amazon.titan-embed-text-v2:0"; U=caselens-local
ACCT=$(aws sts get-caller-identity --query Account --output text); B="caselens-raw-$ACCT"
aws s3api create-bucket --bucket "$B" --region $R --create-bucket-configuration LocationConstraint=$R >/dev/null
aws s3api put-public-access-block --bucket "$B" --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$B" --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
cat > /tmp/p.json <<JSON
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],"Resource":["arn:aws:bedrock:$R::foundation-model/$LLM","arn:aws:bedrock:$R::foundation-model/$EMB"]},
{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":"arn:aws:s3:::$B/*"},
{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::$B"}]}
JSON
aws iam create-user --user-name $U >/dev/null
aws iam put-user-policy --user-name $U --policy-name caselens-min --policy-document file:///tmp/p.json
echo; echo "Bucket: $B"; echo "Model:  $LLM"
echo "Access key (shown ONCE; type it into your own terminal, never paste it in chat):"
aws iam create-access-key --user-name $U --query "AccessKey.[AccessKeyId,SecretAccessKey]" --output text
