from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
import spacy
from difflib import SequenceMatcher
import re

app = Flask(__name__)

nlp = spacy.load("en_core_web_sm")

# ================= DB =================

client = MongoClient("mongodb://localhost:27017")
db = client["ehr_db"]
collection = db["ehr"]

# ================= IGNORE =================

IGNORE = {
    "show","display","list","give","get","find",
    "top","tail","first","last",
    "and","or","between","like","where"
}

# ================= SCHEMA =================

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

# canonical mapping
CANONICAL = {f.lower(): f for f in FIELDS}

# ================= NORMALIZATION =================

def norm(t):
    return " ".join(
        x.lemma_
        for x in nlp(t.lower())
        if x.is_alpha
    )

NORMALIZED_FIELDS = {
    f: norm(f) for f in FIELDS
}

# ================= TYPE =================

def detect_type(f):
    f = f.lower()

    if any(x in f for x in
        ["age","duration","count","number","amount","weight","volume","score"]):
        return "number"

    if "date" in f:
        return "date"

    return "text"

FIELD_RULES = {
    f: {"type": detect_type(f)}
    for f in FIELDS
}

# ================= FIELD MATCH =================

def match_field(text):

    text_norm = norm(text)
    tokens = set(text_norm.split()) - IGNORE

    # exact match
    for f in FIELDS:
        if text_norm == NORMALIZED_FIELDS[f]:
            return f

    # subset match
    for f in FIELDS:
        ft = set(NORMALIZED_FIELDS[f].split())
        if ft and ft.issubset(tokens):
            return f

    # fuzzy match
    best = None
    best_score = 0

    for f in FIELDS:
        s = SequenceMatcher(None, text_norm, NORMALIZED_FIELDS[f]).ratio()
        if s > best_score:
            best_score = s
            best = f

    if best_score > 0.7:
        return best

    return None

# ================= NUMBER =================

NUM = {
    "one":1,"two":2,"three":3,"four":4,"five":5,
    "six":6,"seven":7,"eight":8,"nine":9,"ten":10
}

def parse_num(w):
    try:
        return int(w)
    except:
        return NUM.get(w)

# ================= PARSE =================

def parse_query(q):

    q = q.lower()
    words = q.split()

    limit = None
    mode = "top"

    for i, w in enumerate(words):

        if w in ["top","first"]:
            mode = "top"
            if i+1 < len(words):
                limit = parse_num(words[i+1])

        if w in ["tail","last"]:
            mode = "tail"
            if i+1 < len(words):
                limit = parse_num(words[i+1])

    select = q.split("where")[0]
    parts = select.split(",")

    fields = []

    for p in parts:
        f = match_field(p)
        if f and f not in fields:
            fields.append(f)

    filters = []

    if "where" in q:

        where = q.split("where")[1]
        conds = re.split(r"\band\b|\bor\b", where)
        ops = re.findall(r"\band\b|\bor\b", where)

        for i, c in enumerate(conds):

            field = match_field(c)
            if not field:
                continue

            logic = "AND" if i == 0 else ops[i-1].upper()

            if "between" in c:
                nums = re.findall(r"\d+", c)
                if len(nums) == 2:
                    filters.append({
                        "field": field.lower(),
                        "op": "BETWEEN",
                        "value": nums,
                        "logic": logic
                    })
                    continue

            if "like" in c:
                val = c.split("like")[-1].strip()
                filters.append({
                    "field": field.lower(),
                    "op": "LIKE",
                    "value": val,
                    "logic": logic
                })
                continue

            for w in c.split():
                n = parse_num(w)
                if n is None:
                    continue

                op = "="
                if ">" in c or "greater" in c:
                    op = ">"
                if "<" in c or "less" in c:
                    op = "<"

                filters.append({
                    "field": field.lower(),
                    "op": op,
                    "value": n,
                    "logic": logic
                })

    return fields, filters, limit, mode

# ================= FILTER =================

def apply_filters(record, filters):

    def check(flt):

        field = flt["field"]
        op = flt["op"]
        val = flt["value"]

        rec_val = record.get(field)

        if rec_val in [None, "", "null"]:
            return False

        try:

            if op == "BETWEEN":
                return float(val[0]) <= float(rec_val) <= float(val[1])

            if op == "LIKE":
                return val.lower() in str(rec_val).lower()

            rec_val = float(rec_val)

            if op == ">":
                return rec_val > val
            if op == "<":
                return rec_val < val
            if op == "=":
                return rec_val == val

        except:
            return str(rec_val).lower() == str(val).lower()

        return False

    if not filters:
        return True

    result = check(filters[0])

    for i in range(1, len(filters)):
        logic = filters[i]["logic"]
        curr = check(filters[i])

        if logic == "AND":
            result = result and curr
        else:
            result = result or curr

    return result

# ================= AQL =================

def generate_aql(fields, filters, limit):

    if not fields:
        select_clause = "*"
    else:
        select_clause = ",\n".join(
            f"c/data/items[name/value='{f}']/value AS \"{f}\""
            for f in fields
        )

    aql = f"""
SELECT
{select_clause}
FROM EHR e
CONTAINS COMPOSITION c
""".strip()

    if filters:
        conds = []
        for f in filters:
            conds.append(f"{f['field']} {f['op']} {f['value']}")
        aql += "\nWHERE " + " AND ".join(conds)

    if limit:
        aql += f"\nLIMIT {limit}"

    return aql

# ================= EXPLANATION =================

def build_explanation(fields, filters, limit, mode, query):

    steps = []

    # STEP 1
    if fields:
        steps.append(f"Fetch {', '.join(fields)} from EHR records")
    else:
        steps.append("Fetch all records")

    # STEP 2
    if filters:
        conds = []
        for f in filters:
            conds.append(f"{f['field']} {f['op']} {f['value']}")
        steps.append("Filter records where " + " AND ".join(conds))

    # STEP 3
    if limit:
        steps.append(f"Select {mode} {limit} records")

    # STEP 4 (COUNT)
    if "how many" in query.lower():
        steps.append("Calculate the count of resulting records")

    semantic = "\n".join([
        f"{f} → {FIELD_RULES[f]['type']}"
        for f in fields
    ]) if fields else ""

    lf = f"SELECT {', '.join(fields) if fields else '*'}"

    if filters:
        conds = []
        for f in filters:
            conds.append(f"{f['field']} {f['op']} {f['value']}")
        lf += " WHERE " + " AND ".join(conds)

    if limit:
        lf += f" LIMIT {limit}"

    return {
        "steps": steps,
        "semantic": semantic,
        #"logical_form": lf
    }

# ================= EXTRACT =================

def extract(node, rec):

    if isinstance(node, dict):

        if node.get("type") == "ELEMENT":
            name = node["name"]["value"].lower()
            val = node.get("value", {}).get("magnitude") \
                or node.get("value", {}).get("value")
            rec[name] = val

        for v in node.values():
            extract(v, rec)

    elif isinstance(node, list):
        for i in node:
            extract(i, rec)

# ================= API =================

@app.route("/api/nlp_query", methods=["POST"])
def run():

    try:
        q = request.json.get("query", "")
    except:
        return jsonify({"error": "Invalid request"}), 400

    fields, filters, limit, mode = parse_query(q)

    aql = generate_aql(fields, filters, limit)

    explain = build_explanation(fields, filters, limit, mode, q)

    res = []

    for d in collection.find():

        r = {}
        extract(d, r)

        if not apply_filters(r, filters):
            continue

        row = {}
        for f in fields:
            row[f] = r.get(f.lower())

        res.append(row)

    # COUNT handling
    if "how many" in q.lower():
        res = [{"count": len(res)}]

    if limit and "how many" not in q.lower():
        res = res[:limit] if mode == "top" else res[-limit:]

    return jsonify({
        "aql": aql,
        "results": res,
        "explanation": explain
    })

# ================= ROUTE =================

@app.route("/")
def index():
    return render_template("index.html")

# ================= MAIN =================

if __name__ == "__main__":
    app.run(debug=True)
