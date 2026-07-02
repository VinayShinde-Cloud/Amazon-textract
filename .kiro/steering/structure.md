# Project Structure & Code Organization

## Directory Layout

```
AWS-TextTract/
├── lambda_function.py          # Main Lambda function (single entry point)
├── README.md                   # Setup, deployment, troubleshooting guide
├── invoices/                   # Sample invoice files for testing
│   ├── invoice_1.png
│   ├── invoice_2.png
│   └── invoice_3.png
└── .kiro/                      # Kiro configuration
    └── steering/               # AI guidance documents
        ├── product.md          # Product overview and use cases
        ├── tech.md             # Technology stack and build info
        └── structure.md        # This file
```

## File Descriptions

### `lambda_function.py`
**Main application file.** Single, monolithic Lambda function with all processing logic:

- **AWS Clients** (module-level): Initialized once for performance
  - `s3` - S3 operations
  - `textract` - Textract API
  - `dynamodb` - DynamoDB operations
  - `table` - DynamoDB invoices table reference

- **Core Classes**:
  - `RateLimiter` - Thread-safe rate limiting for Bedrock API calls

- **Core Functions**:
  - `lambda_handler(event, context)` - Entry point, orchestrates entire pipeline
  - `parse_invoice_data(textract_response)` - Extracts structured data from Textract response
  - `insert_into_db(data)` - Persists invoice data to DynamoDB
  - `save_text_to_s3(source_bucket, source_key, lines)` - Saves processed text with fallback strategies
  - `enhance_with_bedrock(text_content)` - AI analysis using Bedrock
  - `invoke_model_with_retry(bedrock_client, model_id, body, max_retries)` - Bedrock invocation with retry logic

### `README.md`
**Comprehensive documentation** covering:
- Architecture diagram and data flow
- Prerequisites and required AWS services
- Step-by-step setup and deployment
- Configuration options and environment variables
- Troubleshooting guide with common errors
- Manual testing procedures
- DynamoDB schema reference

### `invoices/`
**Test data directory** containing sample invoice images for local validation and end-to-end testing.

## Code Organization Patterns

### Separation of Concerns
- **AWS Service Initialization**: Module-level initialization for reuse across invocations
- **Utility Classes**: `RateLimiter` encapsulates cross-cutting rate limiting logic
- **Functional Decomposition**: Each major step (parse, enhance, insert, save) is a separate function
- **Error Handling**: Try-catch blocks at function boundaries with specific error messages

### Naming Conventions
- **Functions**: snake_case (e.g., `parse_invoice_data`, `invoke_model_with_retry`)
- **Classes**: PascalCase (e.g., `RateLimiter`)
- **Constants/Config**: camelCase for parameters (e.g., `max_requests_per_minute`)
- **Variables**: snake_case (e.g., `invoice_data`, `bedrock_rate_limiter`)
- **AWS Resources**: camelCase in boto3 calls, snake_case in Python variables

### Docstring Style
- Google-style docstrings on all functions and classes
- Include: description, Args, Returns, and Raises sections
- Example: see `lambda_handler()` or `invoke_model_with_retry()` in lambda_function.py

### Error Handling Strategy
1. **Service Errors**: Caught, logged with context, propagated or handled gracefully
2. **Transient Failures**: Exponential backoff with jitter for Bedrock throttling
3. **Terminal Failures**: Fail fast (e.g., unsupported file format, daily token quota)
4. **Graceful Degradation**: If Bedrock fails, processing continues; AI analysis marked as unavailable
5. **Fallback Chains**: 4-tier strategy for S3 output with logging at each step

### Lambda-Specific Patterns
- **Cold Start Optimization**: AWS clients initialized at module level (not in lambda_handler)
- **Idempotency**: Skips re-processing already-processed files (checks for `processed-text/` prefix)
- **S3 Event Handling**: Extracts bucket and key from S3 event structure
- **Environment Configuration**: Uses `os.environ` for AWS_REGION and TEXTRACT_OUTPUT_BUCKET

## Configuration & Secrets

### Required AWS Resources
- S3 bucket for invoice uploads (source)
- S3 bucket for processed text (destination, optional but recommended)
- DynamoDB table named `invoices` with `invoice_id` as primary key
- Textract access enabled in region
- Bedrock access to Nova Lite model enabled in region

### Environment Variables
- `AWS_REGION` - AWS region (required, auto-set by Lambda)
- `TEXTRACT_OUTPUT_BUCKET` - S3 bucket for processed text (recommended)

### IAM Role Requirements
Lambda execution role must have permissions for:
- S3 (GetObject, PutObject, HeadBucket)
- Textract (AnalyzeExpense)
- Bedrock (InvokeModel)
- DynamoDB (PutItem)
- CloudWatch Logs (CreateLogGroup, CreateLogStream, PutLogEvents)

## Future Extension Points

- **Additional AI Models**: Easy to add more Bedrock model invocations for different analysis tasks
- **Pipeline Steps**: New processing steps can be inserted into `lambda_handler()`
- **Data Destinations**: New save strategies can be added to `save_text_to_s3()` or new functions
- **Monitoring**: CloudWatch metrics and alarms can be extended with custom metrics
- **Async Processing**: Could be adapted for SNS/SQS-based asynchronous queue processing
- **Caching**: Could cache Textract results to reduce costs and improve performance

## Common Development Tasks

### Adding a New Field Extraction
1. Add field to `invoice_data` dict in `parse_invoice_data()`
2. Add extraction logic from Textract response (SummaryFields or LineItemGroups)
3. Update DynamoDB schema in README.md
4. Update data model comment in tech.md

### Adjusting Rate Limiting
1. Modify `max_requests_per_minute` when creating `bedrock_rate_limiter` instance
2. Test with sample invoices to verify quota compliance
3. Check CloudWatch logs for rate limit behavior

### Handling New File Formats
1. Add extension to `supported_extensions` tuple in `lambda_handler()`
2. Verify Textract supports the format
3. Test with sample file before deploying

