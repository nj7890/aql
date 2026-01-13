from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
import spacy
import re

# ---------------- NLP ----------------
nlp = spacy.load("en_core_web_sm")

# ---------------- Flask ----------------
app = Flask(__name__)

# ---------------- MongoDB ----------------
client = MongoClient("mongodb://localhost:27017")
db = client["ehr_db"]
collection = db["ehr"]

# ---------------- UI ----------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------- Extract ELEMENT names ----------------
def get_all_elements():
    elements = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "ELEMENT":
                elements.add(node["name"]["value"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for i in node:
                walk(i)

    for doc in collection.find({}, {"versions.data": 1}):
        walk(doc)

    return list(elements)

# ---------------- NLP → Structured Query ----------------
def nlp_to_structured(text):
    query_doc = nlp(text.lower())
    field_names = get_all_elements()

    # Build spaCy docs for fields
    field_docs = {f: nlp(f.lower()) for f in field_names}

    query_tokens = {t.lemma_ for t in query_doc if t.is_alpha and not t.is_stop}

    selected_fields = []
    conditions = []
    limit = 100

    # ---- Field selection (semantic overlap) ----
    for field, doc in field_docs.items():
        field_tokens = {t.lemma_ for t in doc if t.is_alpha}
        if field_tokens & query_tokens:
            selected_fields.append(field)

    # ---- Conditions ----
    for i, token in enumerate(query_doc):
        if token.like_num:
            value = float(token.text)

            # look left for operator
            window = query_doc[max(0, i - 3):i]
            op = None
            for w in window:
                if w.lemma_ in {"greater", "above", "more"}:
                    op = ">"
                elif w.lemma_ in {"less", "below", "under"}:
                    op = "<"
                elif w.lemma_ in {"equal", "equals", "is"}:
                    op = "="

            if not op:
                continue

            # bind number to nearest noun
            for noun in reversed(window):
                if noun.pos_ == "NOUN":
                    for field, doc in field_docs.items():
                        if noun.lemma_ in {t.lemma_ for t in doc}:
                            conditions.append({
                                "field": field,
                                "op": op,
                                "value": value
                            })

    # ---- Limit ----
    for i, token in enumerate(query_doc):
        if token.lemma_ == "limit" and i + 1 < len(query_doc):
            if query_doc[i + 1].like_num:
                limit = int(query_doc[i + 1].text)

    return selected_fields, conditions, limit

# ---------------- Clean AQL path generator ----------------
def aql_path(field, numeric=True):
    """
    Generates archetype-style, name-based AQL paths
    """
    if numeric:
        return f"c/data/items[name/value='{field}']/value/magnitude"
    else:
        return f"c/data/items[name/value='{field}']/value/value"

# ---------------- AQL Generator ----------------
def generate_aql(fields, conditions, limit):
    select_parts = []

    for f in fields:
        select_parts.append(
            f"{aql_path(f)} AS \"{f}\""
        )

    select_clause = ",\n  ".join(select_parts) if select_parts else "*"

    aql = f"""
SELECT
  {select_clause}
FROM EHR e
CONTAINS COMPOSITION c
"""

    if conditions:
        where_parts = []
        for cnd in conditions:
            where_parts.append(
                f"{aql_path(cnd['field'])} {cnd['op']} {cnd['value']}"
            )
        aql += "\nWHERE\n  " + " AND\n  ".join(where_parts)

    aql += f"\nLIMIT {limit}"
    return aql.strip()

# ---------------- Mongo value extraction ----------------
def extract_values(node, record):
    if isinstance(node, dict):
        if node.get("type") == "ELEMENT":
            name = node["name"]["value"]
            val = (
                node.get("value", {}).get("magnitude") or
                node.get("value", {}).get("value")
            )
            record[name] = val
        for v in node.values():
            extract_values(v, record)
    elif isinstance(node, list):
        for i in node:
            extract_values(i, record)

# ---------------- NLP Query API ----------------
@app.route("/api/nlp_query", methods=["POST"])
def run_nlp_query():
    text = request.json.get("query", "")

    fields, conditions, limit = nlp_to_structured(text)
    aql = generate_aql(fields, conditions, limit)

    results = []

    for doc in collection.find({}):
        record = {}
        extract_values(doc, record)

        passed = True
        for c in conditions:
            val = record.get(c["field"])
            if val is None:
                passed = False
            elif c["op"] == ">" and not val > c["value"]:
                passed = False
            elif c["op"] == "<" and not val < c["value"]:
                passed = False
            elif c["op"] == "=" and not str(val) == str(c["value"]):
                passed = False

        if passed:
            results.append({f: record.get(f) for f in fields})

    return jsonify({
        "aql": aql,
        "results": results
    })

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(debug=True)
