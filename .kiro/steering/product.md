# TextTract Product Overview

## What It Does

TextTract is a serverless invoice processing pipeline that automatically extracts and analyzes invoice data from document images. It combines AWS Textract (OCR), Bedrock AI, and DynamoDB to process invoices at scale with minimal manual intervention.

## Core Functionality

- **Automatic Triggering**: Lambda function invoked on S3 file upload (invoice_id)
- **Invoice Extraction**: Uses Textract AnalyzeExpense API to extract structured fields (invoice number, dates, total, line items)
- **AI-Powered Analysis**: Bedrock (Nova Lite model) identifies inconsistencies and unusual charges
- **Data Persistence**: Stores extracted data in DynamoDB with indexed query capability
- **Audit Trail**: Saves raw extracted text to S3 for debugging and future reference

## Key Features

1. **Event-Driven Architecture**: Serverless, fully automated pipeline triggered by S3 events
2. **Resilient Error Handling**: Exponential backoff retry logic for API throttling; graceful degradation if Bedrock fails
3. **Rate Limiting**: Custom rate limiter enforces quotas (configurable max requests/minute)
4. **Multi-Strategy S3 Output**: 4 fallback strategies for saving processed text across different bucket configurations
5. **Comprehensive Logging**: CloudWatch logs track processing stages, failures, and retry attempts

## Data Flow

```
S3 Upload (Invoice) 
    ↓
Lambda Event Trigger
    ↓
Textract AnalyzeExpense (Extract fields)
    ↓
Bedrock Analysis (Identify issues)
    ↓
DynamoDB (Store structured data)
    ↓
S3 (Archive raw text)
    ↓
Success Response
```

## Target Use Cases

- Automated expense report processing
- Vendor invoice batch processing and validation
- Invoice reconciliation and auditing
- Accounting system integration
- Large-scale expense automation for enterprises

## Supported File Formats

- PDF, PNG, JPG, JPEG, TIFF

