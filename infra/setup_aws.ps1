<#
 One-time AWS setup for CaseLens (S3 + IAM + Bedrock only, region ap-south-1).
 Run it YOURSELF with an admin-capable profile (not the caselens one):
   .\infra\setup_aws.ps1 -AdminProfile default -LlmModelId openai.gpt-oss-20b-1:0
 It creates: private encrypted S3 bucket, IAM user caselens-local with the least-privilege policy,
 and stores that user's access key straight into the AWS CLI profile "caselens".
 The secret key is never printed. Model access itself must still be enabled in the Bedrock console.
#>
param(
  [Parameter(Mandatory)][string]$AdminProfile,
  [string]$Region = "ap-south-1",
  [string]$LlmModelId = "openai.gpt-oss-20b-1:0",
  [string]$EmbedModelId = "amazon.titan-embed-text-v2:0",
  [string]$UserName = "caselens-local",
  [string]$Profile = "caselens"
)
$ErrorActionPreference = "Stop"
$acct = aws sts get-caller-identity --profile $AdminProfile --query Account --output text
$bucket = "caselens-raw-$acct"
Write-Host "Account $acct, bucket $bucket, region $Region"

# 1. Bucket: private, encrypted
aws s3api create-bucket --bucket $bucket --region $Region --profile $AdminProfile `
  --create-bucket-configuration LocationConstraint=$Region | Out-Null
aws s3api put-public-access-block --bucket $bucket --profile $AdminProfile `
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket $bucket --profile $AdminProfile `
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# 2. Policy: only these two models + this bucket
$policy = @{
  Version = "2012-10-17"
  Statement = @(
    @{ Effect="Allow"; Action=@("bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream");
       Resource=@("arn:aws:bedrock:${Region}::foundation-model/$LlmModelId","arn:aws:bedrock:${Region}::foundation-model/$EmbedModelId") },
    @{ Effect="Allow"; Action=@("s3:GetObject","s3:PutObject"); Resource="arn:aws:s3:::$bucket/*" },
    @{ Effect="Allow"; Action=@("s3:ListBucket"); Resource="arn:aws:s3:::$bucket" }
  )
} | ConvertTo-Json -Depth 6 -Compress
$file = Join-Path $env:TEMP "caselens_policy.json"
[IO.File]::WriteAllText($file, $policy)
aws iam create-user --user-name $UserName --profile $AdminProfile | Out-Null
aws iam put-user-policy --user-name $UserName --policy-name caselens-min --policy-document "file://$file" --profile $AdminProfile
Remove-Item $file

# 3. Access key -> CLI profile, never displayed
$key = aws iam create-access-key --user-name $UserName --profile $AdminProfile | ConvertFrom-Json
aws configure set aws_access_key_id $key.AccessKey.AccessKeyId --profile $Profile
aws configure set aws_secret_access_key $key.AccessKey.SecretAccessKey --profile $Profile
aws configure set region $Region --profile $Profile
$key = $null

Write-Host "`nDone. Put these in .env (no secrets):`nAWS_PROFILE=$Profile`nS3_BUCKET=$bucket`nBEDROCK_LLM_ID=$LlmModelId"
Write-Host "Check: aws sts get-caller-identity --profile $Profile"
