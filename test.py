import json
from pymongo import MongoClient
from bson import ObjectId

# -------------------- CONFIG --------------------
MONGO_URI = "mongodb://localhost:27017"
DATABASE_NAME = "ehr_db"
COLLECTION_NAME = "ehr"
JSON_FILE_PATH = "100 docs.json"


# -------------------- MongoDB --------------------
client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]


# -------------------- Load JSON --------------------
with open(JSON_FILE_PATH, 'r', encoding='utf-8') as file:
    data = json.load(file)


# -------------------- Fix ObjectIds --------------------
def fix_ids(data):
    stack = [data]

    while stack:
        current = stack.pop()

        if isinstance(current, dict):
            if "_id" in current and isinstance(current["_id"], dict):
                if "$oid" in current["_id"]:
                    current["_id"] = ObjectId(current["_id"]["$oid"])

            for value in current.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

        elif isinstance(current, list):
            for item in current:
                stack.append(item)


fix_ids(data)


# -------------------- Insert --------------------
try:
    collection.insert_many(data)
    print("Data inserted successfully.")
except Exception as e:
    print("Error inserting data:", e)
