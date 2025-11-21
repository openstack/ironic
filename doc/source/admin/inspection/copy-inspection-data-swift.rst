Copy inspection data between Swift buckets
==========================================

This script assumes that you have S3 credentials for the buckets.
You only have to configure the 5 configuration parameters.

.. code-block:: python

   import boto3
   import json
   from botocore.exceptions import ClientError

   # Configure your S3 buckets and Ceph endpoint
   SOURCE_BUCKET = ''
   DEST_BUCKET = ''

   # Ceph S3 configuration
   CEPH_ENDPOINT = ''
   CEPH_ACCESS_KEY = ''
   CEPH_SECRET_KEY = ''

   def get_s3_client():
       """Initialize and return S3 client for Ceph"""
       session = boto3.Session(
           aws_secret_access_key=CEPH_SECRET_KEY,
           aws_access_key_id=CEPH_ACCESS_KEY)
       return session.client(
           's3',
           endpoint_url=CEPH_ENDPOINT)

   def list_files_to_process(s3_client, bucket):
       """List all files in bucket that don't end with '-UNPROCESSED'"""
       files = []
       try:
           paginator = s3_client.get_paginator('list_objects_v2')
           for page in paginator.paginate(Bucket=bucket):
               if 'Contents' in page:
                   for obj in page['Contents']:
                       key = obj['Key']
                       if not key.endswith('-UNPROCESSED'):
                           files.append(key)
       except ClientError as e:
           print(f"Error listing files: {e}")
           raise
       return files

   def load_json_from_s3(s3_client, bucket, key):
       """Load and parse JSON file from S3"""
       try:
           response = s3_client.get_object(Bucket=bucket, Key=key)
           content = response['Body'].read().decode('utf-8')
           return json.loads(content)
       except ClientError as e:
           print(f"Error reading {key}: {e}")
           raise
       except json.JSONDecodeError as e:
           print(f"Error parsing JSON from {key}: {e}")
           raise

   def save_json_to_s3(s3_client, bucket, key, data):
       """Save JSON data to S3"""
       try:
           s3_client.put_object(
               Bucket=bucket,
               Key=key,
               Body=json.dumps(data, indent=2),
               ContentType='application/json'
           )
           print(f"Saved: {key}")
       except ClientError as e:
           print(f"Error saving {key}: {e}")
           raise

   def process_files():
       """Main processing function"""
       s3_client = get_s3_client()
       print(f"Fetching files from {SOURCE_BUCKET}...")
       files = list_files_to_process(s3_client, SOURCE_BUCKET)
       print(f"Found {len(files)} files to process")

       # Process each file
       for file_key in files:
           print(f"\nProcessing: {file_key}")

           try:
               # Load JSON data
               data = load_json_from_s3(s3_client, SOURCE_BUCKET, file_key)

               # Split data
               inventory = data.pop('inventory', None)
               plugin = data

               # Check if inventory key existed
               if inventory is None:
                   print(f"Warning: 'inventory' key not found in {file_key}")

               # Generate output filenames
               inventory_key = f"{file_key}-inventory"
               plugin_key = f"{file_key}-plugin"

               # Save split files
               if inventory is not None:
                   save_json_to_s3(s3_client, DEST_BUCKET, inventory_key, inventory)
               if plugin is not None:
                   save_json_to_s3(s3_client, DEST_BUCKET, plugin_key, plugin)

           except Exception as e:
               print(f"Failed to process {file_key}: {e}")
               continue

       print("\nProcessing complete!")

   if __name__ == "__main__":
       process_files()
