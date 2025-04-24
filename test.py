import json
from pymongo import MongoClient

# --- CONFIG ---
MONGO_URI = "mongodb://localhost:27017"  # Replace with your MongoDB URI
DATABASE_NAME = "ehr_db"
COLLECTION_NAME = "ehr"
JSON_FILE_PATH = "C:\\Users\\Research Work\\Downloads\\100 docs.json"  # Path to your JSON file

from pymongo import MongoClient
import json
from bson import ObjectId

# MongoDB connection
client = MongoClient("mongodb://localhost:27017")
db = client["ehr_db"]
collection = db["ehr"]

# Load JSON data
with open('100 docs.json', 'r', encoding='utf-8') as file:
    data = json.load(file)
def fix_ids(data):
    # Create a stack for processing the data (avoid recursion)
    stack = [data]
    
    while stack:
        current = stack.pop()
        
        if isinstance(current, dict):
            if "_id" in current:
                # Check if _id is in $oid format
                if isinstance(current["_id"], dict) and "$oid" in current["_id"]:
                    current["_id"] = ObjectId(current["_id"]["$oid"])
            
            # Add nested dictionaries to the stack for processing
            for key, value in current.items():
                if isinstance(value, (dict, list)):
                    stack.append(value)
        
        elif isinstance(current, list):
            # Add items in the list to the stack for processing
            for item in current:
                stack.append(item)

# Fix the IDs in the data
fix_ids(data)

# Insert the data into MongoDB
try:
    collection.insert_many(data)
    print("Data inserted successfully.")
except Exception as e:
    print("Error inserting data:", e)
