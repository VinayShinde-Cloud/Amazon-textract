# Technology Stack & Architecture

## Core Technologies

### Language & Runtime
- **Python 3.x** - Lambda runtime (event-driven, serverless execution)
- **Boto3** - AWS SDK for Python (all AWS service interactions)
- **Botocore** - Lower-level AWS service error handling and exceptions

### AWS Services
- **Lambda** - Serverless compute, triggered by S3 events
- **S3** - Object storage (invoice uploads, processed text backup)
- **Textract** - Managed OCR service (AnalyzeExpense API for invoice analysis)
- **Bedrock** - Managed AI inference (Nova Lite model for analysis)
- **DynamoDB** - NoSQL database for structured invoice metadata
- **CloudWatch** - Logging, monitoring, and debugging

### Key Libraries & Dependencies
- `boto3` - AWS SDK
- `botocore.exceptions.ClientError` - AWS service error handling
- `json` - Request/response serialization
- `threading.Lock` - Thread-safe rate limiting
- `time` - Delay and rate limit timing
- `random` - Jitter for exponential backoff
- `os` - Environment variable access

## Build & Deployment

### Local Development
No build step required (Python is interpreted). To prepare for Lambda deployment:
1. Ensure Boto3 is installed: `pip install boto3`
2. Review code against [AWS Lambda best practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
3. Validate file format support and IAM permissions

### Deployment
- **Manual**: Upload `lambda_function.py` directly to AWS Lambda console
- **Infrastructure as Code**: Use AWS SAM, CloudFormation, or Terraform
- **Environment Variables**: Configure required variables in Lambda configuration

### Testing
- **Unit Testing**: Test individual functions (parse_invoice_data, rate limiting)
- **Integration Testing**: Test against actual AWS services (may incur AWS costs)
- **Manual Testing**: Upload sample invoices to S3 and verify end-to-end flow with CloudWatch logs

### Common Commands

```bash
# Upload test invoice to S3
aws s3 cp invoices/invoice_1.png s3://your-source-bucket/

# View Lambda CloudWatch logs in real-time
aws logs tail /aws/lambda/your-function-name --follow

# Scan DynamoDB for processed invoices
aws dynamodb scan --table-name invoices --limit 10

# List processed text files in output bucket
aws s3 ls s3://textract-project-ml-ai-XXXXXXXX/ --recursive

# Check Lambda function details
aws lambda get-function --function-name your-function-name
```

## Configuration

### Required Environment Variables
- `AWS_REGION` - AWS region (auto-set by Lambda, e.g., `us-east-1`)
- `TEXTRACT_OUTPUT_BUCKET` - S3 bucket for processed text output (recommended)

### IAM Permissions Required
```
s3:GetObject, s3:PutObject, s3:HeadBucket
textract:AnalyzeExpense
bedrock:InvokeModel
dynamodb:PutItem
logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents
```

## Performance Considerations

### Rate Limiting
- Bedrock has quota limits (default: 10 requests/minute for Nova Lite)
- Custom `RateLimiter` class enforces configurable requests per minute
- Adjust `max_requests_per_minute` parameter based on Bedrock quota

### Retry Strategy
- Exponential backoff with jitter for transient Bedrock throttling errors
- Maximum 4 retries for API calls
- Daily token quota exhaustion fails immediately (retries won't help)
- Non-throttling errors fail fast without retry

### Timeout Considerations
- Lambda timeout should be set to 5+ minutes for full processing pipeline
- S3 uploads and Textract calls can be slower for large/complex documents

## Data Models

### Invoice Data Structure (DynamoDB)
```python
{
    'invoice_id': str,              # Primary key
    'invoice_number': str,          # Extracted invoice number
    'due_date': str,                # Due date from invoice
    'receipt_date': str,            # Receipt/issue date
    'total': str,                   # Total amount
    'line_items': [                 # Array of purchased items
        {'item': str, 'price': str},
        ...
    ],
    'llm_analysis': str             # Bedrock AI analysis (inconsistencies, unusual charges)
}
```

### Textract Response Structure
- `ExpenseDocuments[0].SummaryFields` - High-level invoice metadata (date, total, invoice ID)
- `ExpenseDocuments[0].LineItemGroups` - Itemized line items with descriptions and prices
- `Blocks[BlockType='LINE']` - Raw extracted text lines for Bedrock analysis

## Error Handling Strategy

1. **Service Errors**: Caught and logged with context
2. **Transient Failures** (Bedrock throttling): Retry with exponential backoff
3. **Terminal Failures** (token quota, format validation): Fail fast without retry
4. **Graceful Degradation**: If Bedrock fails, processing continues without AI analysis
5. **Fallback Chains**: 4-strategy approach for S3 output with intelligent fallbacks

