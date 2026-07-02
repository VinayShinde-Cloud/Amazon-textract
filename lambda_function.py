import json
import boto3
import os
import time
import random
from botocore.exceptions import ClientError
from threading import Lock

# AWS Configuration
region = os.environ['AWS_REGION']
s3 = boto3.client('s3')
textract = boto3.client('textract', region_name=region)
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('invoices')

# Rate Limiter for Bedrock API calls
class RateLimiter:
    """
    Rate limiter to prevent exceeding Bedrock API limits.
    Ensures we don't make too many requests per minute.
    """
    def __init__(self, max_requests_per_minute):
        self.max_requests = max_requests_per_minute
        self.requests = []
        self.lock = Lock()
    
    def wait_if_needed(self):
        """Wait if we've hit the rate limit."""
        with self.lock:
            now = time.time()
            # Remove requests older than 1 minute
            self.requests = [req_time for req_time in self.requests if now - req_time < 60]
            
            if len(self.requests) >= self.max_requests:
                sleep_time = 60 - (now - self.requests[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
            self.requests.append(now)

# Initialize rate limiter (adjust max_requests based on your Bedrock quota)
bedrock_rate_limiter = RateLimiter(max_requests_per_minute=10)

def invoke_model_with_retry(bedrock_client, model_id, body, max_retries=4):
    """
    Invoke Bedrock model with exponential backoff retry logic.
    
    Args:
        bedrock_client: Boto3 Bedrock runtime client
        model_id: The model ID to invoke
        body: JSON string of the request body
        max_retries: Maximum number of retry attempts
    
    Returns:
        Response from Bedrock API
    
    Raises:
        ClientError: If all retries are exhausted or non-throttling error occurs
    """
    for attempt in range(max_retries + 1):
        try:
            # Wait if needed based on rate limiting
            bedrock_rate_limiter.wait_if_needed()
            
            response = bedrock_client.invoke_model(
                modelId=model_id,
                body=body
            )
            return response
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'ThrottlingException':
                # Daily token quota exhausted — retrying won't help, fail immediately
                if 'tokens per day' in str(e).lower():
                    print("Daily token quota exceeded. Skipping retries.")
                    raise e
                if attempt < max_retries:
                    # Exponential backoff with jitter
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    print(f"ThrottlingException: Retry {attempt + 1}/{max_retries} after {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Max retries ({max_retries}) exceeded for ThrottlingException")
                    raise e
            else:
                # For non-throttling errors, raise immediately
                print(f"Bedrock error: {error_code} - {str(e)}")
                raise e
    
    # This should never be reached, but just in case
    raise Exception("Unexpected exit from retry loop")

def lambda_handler(event, context):
    """
    Main Lambda handler function invoked when a file is uploaded to S3.
    
    Args:
        event: S3 event notification containing bucket and object information
        context: Lambda context object
    
    Returns:
        dict: Response with status code and message
    """
    try:
        # Extract bucket and key from S3 event
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
        
        print(f"Processing invoice: {key} from bucket: {bucket}")

        # Ignore files written back by this function to avoid re-triggering
        if key.startswith('processed-text/'):
            print(f"Skipping processed text file: {key}")
            return {'statusCode': 200, 'body': json.dumps('Skipped processed text file.')}

        # Validate file format before calling Textract
        supported_extensions = ('.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif')
        file_ext = key.lower().rsplit('.', 1)[-1]
        if not key.lower().endswith(supported_extensions):
            raise ValueError(f"Unsupported file format '.{file_ext}'. Textract AnalyzeExpense supports: PDF, PNG, JPG, TIFF")

        # Call Amazon Textract to analyze the invoice
        response = textract.analyze_expense(Document={
            'S3Object': {
                'Bucket': bucket,
                'Name': key
            }
        })
        
        # Parse the Textract response
        invoice_data_lines = parse_invoice_data(response)
        data = invoice_data_lines[0]
        lines = invoice_data_lines[1]
        
        # Enhance with Bedrock AI analysis
        try:
            rock = enhance_with_bedrock(lines)
            data['llm_analysis'] = rock['output']['message']['content'][0]['text']
        except Exception as bedrock_error:
            # If Bedrock fails, continue with processing but log the error
            print(f"Bedrock analysis failed: {str(bedrock_error)}")
            data['llm_analysis'] = f"Analysis unavailable: {str(bedrock_error)}"
        
        # Insert data into DynamoDB
        insert_into_db(data)
        
        # Save extracted text to S3 for future reference
        save_text_to_s3(bucket, key, lines)
        
        print(f"Successfully processed invoice: {key}")
        
        return {
            'statusCode': 200,
            'body': json.dumps('Invoice successfully processed!')
        }
    
    except Exception as e:
        print(f"Error processing invoice: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error processing invoice: {str(e)}')
        }

def parse_invoice_data(textract_response):
    """
    Parse Textract response to extract structured invoice data.
    
    Args:
        textract_response: JSON response from Textract analyze_expense API
    
    Returns:
        tuple: (invoice_data dict, list of text lines)
    """
    # Initialize invoice data structure
    invoice_data = {
        'invoice_id': None,
        'due_date': None,
        'receipt_date': None,
        'invoice_number': None,
        'total': None,
        'line_items': [],
        'llm_analysis': None
    }
    
    # Extract summary fields
    expense_doc = textract_response['ExpenseDocuments'][0]
    for field in expense_doc['SummaryFields']:
        field_type = field['Type']['Text']
        
        if field_type == 'DUE_DATE':
            invoice_data['due_date'] = field['ValueDetection']['Text']
        elif field_type == 'INVOICE_RECEIPT_DATE':
            invoice_data['receipt_date'] = field['ValueDetection']['Text']
        elif field_type == 'INVOICE_RECEIPT_ID':
            invoice_data['invoice_number'] = field['ValueDetection']['Text']
            invoice_data['invoice_id'] = field['ValueDetection']['Text']
        elif field_type == 'TOTAL':
            invoice_data['total'] = field['ValueDetection']['Text']
    
    # Extract line items
    items = []
    items_prices = []
    
    for field in expense_doc['LineItemGroups']:
        for subfield in field['LineItems']:
            if subfield['LineItemExpenseFields']:
                for expense_field in subfield['LineItemExpenseFields']:
                    field_type = expense_field['Type']['Text']
                    
                    if field_type == 'ITEM':
                        items.append(expense_field['ValueDetection']['Text'])
                    elif field_type == 'PRICE':
                        items_prices.append(expense_field['ValueDetection']['Text'])
    
    # Combine items with prices
    for item, price in zip(items, items_prices):
        invoice_data['line_items'].append({'item': item, 'price': price})
    
    # Extract all text lines
    lines = []
    for field in expense_doc['Blocks']:
        if field['BlockType'] == 'LINE':
            lines.append(field['Text'])
    
    return (invoice_data, lines)

def insert_into_db(data):
    """
    Insert invoice data into DynamoDB table.
    
    Args:
        data: Dictionary containing invoice data
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        response = table.put_item(Item=data)
        print(f"Successfully inserted invoice {data.get('invoice_id')} into DynamoDB")
        return True
    except Exception as e:
        print(f"DynamoDB insertion error: {str(e)}")
        return False

def save_text_to_s3(source_bucket, source_key, lines):
    """
    Save extracted text to S3 bucket with multiple fallback strategies.
    
    Args:
        source_bucket: Original bucket where invoice was uploaded
        source_key: Original key/filename of the invoice
        lines: List of text lines extracted from invoice
    
    Returns:
        bool: True if successful, False otherwise
    """
    object_txt_key = source_key.split('.')[0]
    text_content = '\n'.join(lines)
    
    # Strategy 1: Try to use environment variable for destination bucket
    destination_bucket = os.environ.get('TEXTRACT_OUTPUT_BUCKET')
    
    if destination_bucket:
        try:
            s3.put_object(
                Bucket=destination_bucket,
                Key=f'{object_txt_key}.txt',
                Body=text_content
            )
            print(f"Saved text to configured bucket: {destination_bucket}/{object_txt_key}.txt")
            return True
        except ClientError as e:
            print(f"Failed to save to configured bucket {destination_bucket}: {str(e)}")
    
    # Strategy 2: Try the original naming pattern
    try:
        bucket_random_number = source_bucket.split('-')[-1]
        destination_bucket = f'textract-ml-ai-123{bucket_random_number}'
        
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=destination_bucket)
            # Bucket exists, save the file
            s3.put_object(
                Bucket=destination_bucket,
                Key=f'{object_txt_key}.txt',
                Body=text_content
            )
            print(f"Saved text to destination bucket: {destination_bucket}/{object_txt_key}.txt")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                print(f"Destination bucket does not exist: {destination_bucket}")
            else:
                print(f"Error checking bucket {destination_bucket}: {str(e)}")
    except Exception as e:
        print(f"Error with naming pattern strategy: {str(e)}")
    
    # Strategy 3: Save to the same bucket as source (in a subfolder)
    try:
        s3.put_object(
            Bucket=source_bucket,
            Key=f'processed-text/{object_txt_key}.txt',
            Body=text_content
        )
        print(f"Saved text to source bucket: {source_bucket}/processed-text/{object_txt_key}.txt")
        return True
    except ClientError as e:
        print(f"Failed to save to source bucket: {str(e)}")
    
    # Strategy 4: Last resort - try a default bucket name
    try:
        default_bucket = 'textract-processed-invoices'
        s3.put_object(
            Bucket=default_bucket,
            Key=f'{object_txt_key}.txt',
            Body=text_content
        )
        print(f"Saved text to default bucket: {default_bucket}/{object_txt_key}.txt")
        return True
    except ClientError as e:
        print(f"Failed to save to default bucket: {str(e)}")
    
    print("WARNING: Could not save extracted text to any S3 bucket")
    return False

def enhance_with_bedrock(text_content):
    """
    Use Amazon Bedrock to analyze invoice for inconsistencies and unusual charges.
    Includes retry logic with exponential backoff for throttling errors.
    
    Args:
        text_content: List of text lines from the invoice
    
    Returns:
        dict: Bedrock response containing AI analysis
    """
    bedrock_runtime = boto3.client('bedrock-runtime')
    model_id = 'us.amazon.nova-micro-v1:0'
    
    # Create analysis prompt
    prompt = f"""
    From the invoice text below, please try to check for any inconsistencies in the data and also if there are any unusual charges:
    
    Invoice text: {text_content}
    """
    
    # Prepare request body
    body = json.dumps({
        "inferenceConfig": {
            "maxTokens": 1000,
            "temperature": 0.7,
            "topP": 0.9,
            "stopSequences": []
        },
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    })
    
    # Invoke model with retry logic
    response = invoke_model_with_retry(
        bedrock_client=bedrock_runtime,
        model_id=model_id,
        body=body,
        max_retries=4
    )
    
    # Parse and return response
    response_body = json.loads(response.get('body').read())
    return response_body
