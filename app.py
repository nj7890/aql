from flask import Flask, render_template, request, jsonify, session
from pymongo import MongoClient
import spacy
import time

# ================= INIT =================
app = Flask(__name__)
app.secret_key = "ehr-asst-secret"
nlp = spacy.load("en_core_web_sm")

ASSISTANT_NAME = "EHR-Asst"

# ================= DATABASE =================
client = MongoClient("mongodb://localhost:27017")
db = client["ehr_db"]
collection = db["ehr"]

# ================= SCHEMA EXTRACTION =================
def extract_schema():
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

FIELDS = extract_schema()

# ================= NORMALIZATION =================
def normalize_text(text):
    return " ".join(t.lemma_ for t in nlp(text.lower()) if t.is_alpha)

NORMALIZED_FIELDS = {f: normalize_text(f) for f in FIELDS}

# ================= UI =================
@app.route("/")
def index():
    return render_template("index.html", assistant=ASSISTANT_NAME)

# ================= SESSION CONTEXT =================
def get_context():
    if "ctx" not in session:
        session["ctx"] = {
            "select_fields": [],
            "filters": {},
            "limit": 10
        }
    return session["ctx"]

@app.route("/api/reset_context", methods=["POST"])
def reset_context():
    session.pop("ctx", None)
    return jsonify({"status": "reset"})

# ================= VALUE EXTRACTION =================
def extract_values(node, record):
    if isinstance(node, dict):
        if node.get("type") == "ELEMENT":
            name = node["name"]["value"]
            val = node.get("value", {}).get("magnitude") or node.get("value", {}).get("value")
            try:
                record[name] = float(val)
            except (TypeError, ValueError):
                record[name] = val
        for v in node.values():
            extract_values(v, record)
    elif isinstance(node, list):
        for i in node:
            extract_values(i, record)

# ================= NLP → STRUCTURED =================
def nlp_to_structured(query, default_limit=10):
    query = query.lower()

    if " where " in query:
        select_text, where_text = query.split(" where ", 1)
    else:
        select_text, where_text = query, ""

    doc = nlp(query)
    where_doc = nlp(where_text)

    # -------- SELECT --------
    normalized_query = normalize_text(select_text)
    select_fields = [
        f for f in sorted(FIELDS, key=len, reverse=True)
        if NORMALIZED_FIELDS[f] in normalized_query
    ]

    # -------- WHERE --------
    filters = {}
    total_conditions = 0
    valid_conditions = 0

    for token in where_doc:
        if token.like_num:
            total_conditions += 1
            value = float(token.text)
            op = None

            for left in token.lefts:
                if left.lemma_ in {"great", "above", "more"}:
                    op = ">"
                elif left.lemma_ in {"less", "below"}:
                    op = "<"
                elif left.lemma_ in {"equal", "equals", "is"}:
                    op = "="

            if not op:
                continue

            context_tokens = {t.lemma_ for t in token.subtree if t.is_alpha}

            for field, norm in NORMALIZED_FIELDS.items():
                if set(norm.split()) & context_tokens:
                    filters.setdefault(field, []).append((op, value))
                    valid_conditions += 1

    # -------- LIMIT --------
    limit = default_limit
    for i, token in enumerate(doc):
        if token.like_num:
            window = doc[max(i - 3, 0): min(i + 4, len(doc))]
            if {t.lemma_ for t in window} & {"top", "first", "limit", "only"}:
                limit = int(token.text)
                break

    return select_fields, filters, limit, total_conditions, valid_conditions

# ================= AQL GENERATION =================
def generate_aql(fields, filters, limit):
    if not fields:
        fields = [FIELDS[0]]

    select_clause = ",\n  ".join(
        f"c/data/items[name/value='{f}']/value AS \"{f}\""
        for f in fields
    )

    aql = f"""
SELECT
  {select_clause}
FROM EHR e
CONTAINS COMPOSITION c
"""

    if filters:
        where_parts = [
            f"c/data/items[name/value='{f}']/value {op} {val}"
            for f, conds in filters.items()
            for op, val in conds
        ]
        aql += "\nWHERE\n  " + " AND\n  ".join(where_parts)

    aql += f"\nLIMIT {limit}"
    return aql.strip()

# ================= API =================
@app.route("/api/nlp_query", methods=["POST"])
def run_query():
    start_time = time.perf_counter()

    user_query = request.json.get("query", "").strip()
    ctx = get_context()

    fields, filters, limit, total_conds, valid_conds = nlp_to_structured(user_query)

    # Merge SELECT
    for f in fields:
        if f not in ctx["select_fields"]:
            ctx["select_fields"].append(f)

    # Merge WHERE
    for f, conds in filters.items():
        ctx["filters"].setdefault(f, []).extend(conds)

    # Update LIMIT only if mentioned
    if limit != 10:
        ctx["limit"] = limit

    session["ctx"] = ctx

    aql = generate_aql(ctx["select_fields"], ctx["filters"], ctx["limit"])

    # -------- EXECUTION --------
    results = []
    for doc in collection.find({}):
        record = {}
        extract_values(doc, record)

        passed = True
        for field, conds in ctx["filters"].items():
            if field not in record or not isinstance(record[field], (int, float)):
                passed = False
                break
            for op, val in conds:
                if op == ">" and not record[field] > val:
                    passed = False
                if op == "<" and not record[field] < val:
                    passed = False
                if op == "=" and not record[field] == val:
                    passed = False

        if passed:
            results.append({f: record.get(f) for f in ctx["select_fields"]})

        if len(results) >= ctx["limit"]:
            break

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # -------- METRICS --------
    metrics = {
        "field_mapping_accuracy": round(
            len(fields) / max(len(ctx["select_fields"]), 1), 2
        ),
        "condition_extraction_accuracy": round(
            valid_conds / max(total_conds, 1), 2
        ),
        "query_success": len(results) > 0,
        "latency_ms": latency_ms
    }

    return jsonify({
        "assistant": ASSISTANT_NAME,
        "context": ctx,
        "aql": aql,
        "results": results,
        "metrics": metrics
    })

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
