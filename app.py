from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
import spacy

# ---------------- Init ----------------
app = Flask(__name__)
nlp = spacy.load("en_core_web_sm")

# ---------------- MongoDB ----------------
client = MongoClient("mongodb://localhost:27017")
db = client["ehr_db"]
collection = db["ehr"]

# ---------------- UI ----------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------- Extract all ELEMENT fields ----------------
def get_all_element_fields():
    fields = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "ELEMENT":
                fields.add(node["name"]["value"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for i in node:
                walk(i)

    for doc in collection.find({}, {"versions.data": 1}):
        walk(doc)

    return sorted(fields)

# ---------------- Build semantic index ----------------
def build_field_index(fields):
    index = {}
    for field in fields:
        tokens = {
            t.lemma_
            for t in nlp(field.lower())
            if t.is_alpha
        }
        index[field] = tokens
    return index

# ---------------- Extract values ----------------
def extract_values(node, record):
    if isinstance(node, dict):
        if node.get("type") == "ELEMENT":
            name = node["name"]["value"]
            value = (
                node.get("value", {}).get("magnitude")
                or node.get("value", {}).get("value")
            )
            record[name] = value
        for v in node.values():
            extract_values(v, record)
    elif isinstance(node, list):
        for i in node:
            extract_values(i, record)

# ---------------- NLP → Structured (CONSISTENT SELECT + WHERE) ----------------
def nlp_to_structured(query):
    query = query.lower()

    # ---- split SELECT / WHERE ----
    if " where " in query:
        select_text, where_text = query.split(" where ", 1)
        #print(where_text)
    else:
        select_text = query
        where_text = ""

    select_doc = nlp(select_text)
    where_doc = nlp(where_text)
    
    select_tokens = {t.lemma_ for t in select_doc if t.is_alpha}
    where_tokens = {t.lemma_ for t in where_doc if t.is_alpha}
    print(where_tokens)
    all_fields = get_all_element_fields()
    field_index = build_field_index(all_fields)

    # ---- SELECT fields (already working) ----
    select_fields = [
        field
        for field, tokens in field_index.items()
        if tokens & select_tokens
    ]

    # ---- WHERE fields (SAME algorithm) ----
    where_fields = [
        field
        for field, tokens in field_index.items()
        if tokens & where_tokens
    ]

    # ---- WHERE conditions (bind operator + value to matched fields) ----
    filters = {}

    for token in where_doc:
        if token.like_num:
            value = int(token.text)

            # operator detection
            op = None
            for w in where_doc:
                if w.lemma_ in {"great", "above", "more"}:
                    op = ">"
                elif w.lemma_ in {"less", "below"}:
                    op = "<"
                elif w.lemma_ in {"equal", "equals", "is"}:
                    op = "="

            if not op:
                continue

            # bind to WHERE fields using SAME token matching
            for field in where_fields:
                if field_index[field] & where_tokens:
                    filters[field] = (op, value)

    return select_fields, filters

# ---------------- AQL Generator ----------------
def generate_aql(fields, filters, limit=10):
    select_clause = ",\n  ".join(
        [f"c/data/items[name/value='{f}']/value AS \"{f}\"" for f in fields]
    )

    aql = f"""
SELECT
  {select_clause}
FROM EHR e
CONTAINS COMPOSITION c
"""

    if filters:
        where_clause = []
        for field, (op, value) in filters.items():
            where_clause.append(
                f"c/data/items[name/value='{field}']/value {op} {value}"
            )
        aql += "\nWHERE\n  " + " AND\n  ".join(where_clause)

    aql += f"\nLIMIT {limit}"
    return aql.strip()

# ---------------- API ----------------
@app.route("/api/nlp_query", methods=["POST"])
def run_nlp_query():
    query = request.json.get("query", "")

    select_fields, filters = nlp_to_structured(query)
    aql = generate_aql(select_fields, filters)

    results = []

    for doc in collection.find({}):
        record = {}
        extract_values(doc, record)

        passed = True
        for field, (op, value) in filters.items():
            if field not in record:
                passed = False
                break
            if op == ">" and not record[field] > str(value):
                passed = False
            if op == "<" and not record[field] < str(value):
                passed = False
            if op == "=" and not record[field] == str(value):
                passed = False

        if passed:
            results.append({f: record.get(f) for f in select_fields})

    return jsonify({
        "select_fields": select_fields,
        "filters": filters,
        "aql": aql,
        "results": results
    })

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(debug=True)
