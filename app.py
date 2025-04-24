from flask import Flask, render_template, request, redirect
import os, json
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId

app = Flask(__name__)

client = MongoClient("mongodb://localhost:27017")
db = client["ehr_web"]
compositions = db["compositions"]

TEMPLATE_DIR = "openehr_templates/"

def get_all_templates():
    return [f for f in os.listdir(TEMPLATE_DIR) if f.endswith('.json')]

def get_template_fields(template_name):
    try:
        with open(os.path.join(TEMPLATE_DIR, template_name), 'r') as f:
            data = json.load(f)
            return list(data.get("fields", {}).keys())
    except:
        return []

@app.route('/')
def index():
    templates = get_all_templates()
    return render_template("index.html", templates=templates)

@app.route('/load_fields', methods=['POST'])
def load_fields():
    template = request.form['template']
    fields = get_template_fields(template)
    return render_template("index.html", templates=get_all_templates(), selected_template=template, fields=fields)

@app.route('/submit', methods=['POST'])
def submit():
    template = request.form['template']
    field_data = {k: v for k, v in request.form.items() if k != 'template'}
    composition = {
        "ehr_id": ObjectId(),
        "template_id": template,
        "data": field_data,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    compositions.insert_one(composition)
    return redirect('/')

@app.route('/query', methods=['GET', 'POST'])
def query():
    results = []
    error = None
    if request.method == 'POST':
        try:
            query_json = json.loads(request.form['query'])
            results = list(compositions.find(query_json))
        except Exception as e:
            error = str(e)
    return render_template("query.html", results=results, error=error)

if __name__ == '__main__':
    app.run(debug=True)
