from flask import Flask, render_template, request, jsonify
from pymongo.errors import DuplicateKeyError
from database import db, insert_patient, insert_composition, query_compositions
from bson.objectid import ObjectId

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/patients", methods=["GET"])
def list_patients():
    pats = [{"_id": str(p["_id"]), 
             "gov_id": p.get("gov_id"), 
             "name": p.get("name")}
            for p in db["patients"].find()]
    return jsonify(pats)

@app.route("/add_patient", methods=["POST"])
def add_patient():
    data = request.form.to_dict()
    # ensure correct typing for age
    if data.get("age"):
        data["age"] = int(data["age"])
    try:
        insert_patient(data)
        return jsonify({"status": "success"})
    except DuplicateKeyError:
        return jsonify({
            "status": "error",
            "message": "A patient with this Government ID already exists."
        }), 409

@app.route("/upload_template", methods=["POST"])
def upload_template():
    file = request.files["template"]
    template_data = file.read().decode("utf-8")
    db["templates"].insert_one({
        "name": file.filename,
        "content": template_data
    })
    return jsonify({"status": "uploaded"})

@app.route("/templates", methods=["GET"])
def list_templates():
    temps = [{"_id": str(t["_id"]), "name": t.get("name")}
             for t in db["templates"].find()]
    return jsonify(temps)

@app.route("/put_data", methods=["POST"])
def put_data():
    data = request.json
    # expect data to include ehr_id, template_id, data
    insert_composition(data)
    return jsonify({"status": "inserted"})

@app.route("/query", methods=["POST"])
def query():
    filters = request.json
    result = query_compositions(filters)
    # stringify ObjectIds
    for r in result:
        r["_id"]    = str(r["_id"])
        r["ehr_id"] = str(r["ehr_id"])
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
