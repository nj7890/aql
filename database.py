from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from datetime import datetime
from bson.objectid import ObjectId

# Connect & ensure unique gov_id on patients
client = MongoClient("mongodb://localhost:27017")
db = client["ehr_system"]
db["patients"].create_index("gov_id", unique=True)

def insert_patient(data):
    """
    data: { name, age, gender, location, gov_id }
    Raises DuplicateKeyError if gov_id already exists.
    """
    return db["patients"].insert_one(data)

def insert_composition(data):
    data["created_at"] = datetime.utcnow()
    return db["compositions"].insert_one(data)

def query_compositions(filters):
    q = {}
    if filters.get("ehr_id"):
        q["ehr_id"] = ObjectId(filters["ehr_id"])
    if filters.get("template_id"):
        q["template_id"] = filters["template_id"]
    for cond in filters.get("conditions", []):
        path = cond["path"]
        op   = cond["op"]
        val  = cond["value"]
        mongo_op = {
            "=":  "$eq", "!=": "$ne",
            ">":  "$gt", "<":  "$lt",
            ">=": "$gte","<=": "$lte"
        }.get(op, "$eq")
        q[path] = {mongo_op: val}
    return list(db["compositions"].find(q))
