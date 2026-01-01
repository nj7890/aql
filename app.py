from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient

app = Flask(__name__)

# MongoDB connection
client = MongoClient("mongodb://localhost:27017")
db = client["ehr_db"]
collection = db["ehr"]


# -------------------- UI --------------------
@app.route('/')
def index():
    return render_template('index.html')


# -------------------- API: Patients --------------------
@app.route('/api/patients', methods=['GET'])
def get_patients():
    ehr_ids = collection.distinct("owner_id.id.value")
    return jsonify(ehr_ids)


# -------------------- API: Compositions --------------------
@app.route('/api/compositions', methods=['POST'])
def get_compositions():
    ehr_ids = request.json.get('ehr_ids', [])

    pipeline = [
        {'$match': {'owner_id.id.value': {'$in': ehr_ids}}},
        {'$group': {
            '_id': '$versions.data.archetype_node_id',
            'name': {'$first': '$versions.data.name.value'}
        }}
    ]

    res = list(collection.aggregate(pipeline))
    return jsonify([
        {'archetype_id': r['_id'], 'name': r['name']}
        for r in res
    ])


# -------------------- Helpers --------------------
def extract_fields(node, out_set):
    if not isinstance(node, dict):
        return

    if node.get('type') == 'ELEMENT':
        out_set.add(node['name']['value'])

    elif 'items' in node:
        for child in node['items']:
            extract_fields(child, out_set)


def extract_values(node, out_dict):
    if not isinstance(node, dict):
        return

    if node.get('type') == 'ELEMENT':
        name = node['name']['value']
        val = (
            node.get('value', {}).get('magnitude') or
            node.get('value', {}).get('value')
        )
        out_dict[name] = val

    elif 'items' in node:
        for child in node['items']:
            extract_values(child, out_dict)


# -------------------- API: Fields --------------------
@app.route('/api/fields', methods=['POST'])
def get_fields():
    ehr_id = request.json.get('ehr_id')
    archetype_id = request.json.get('archetype_id')

    doc = collection.find_one({
        'owner_id.id.value': ehr_id,
        'versions.data.archetype_node_id': archetype_id
    })

    if not doc:
        return jsonify([])

    composition = doc['versions']['data']
    if composition.get('archetype_node_id') != archetype_id:
        return jsonify([])

    fields = set()
    for entry in composition.get('content', []):
        for cluster in entry.get('data', {}).get('items', []):
            extract_fields(cluster, fields)

    return jsonify(sorted(fields))


# -------------------- AQL Generator --------------------
def generate_aql(ehr_ids, archetype_id, elements, filters, limit, offset, sort):
    select_clause = []

    for el in elements:
        field = el['field']
        alias = el.get('alias', field)
        select_clause.append(f"c/{field} AS {alias}")

    select_str = ", ".join(select_clause) if select_clause else "*"

    aql = f"""
SELECT {select_str}
FROM EHR e
CONTAINS COMPOSITION c[{archetype_id}]
WHERE e/ehr_id/value MATCHES {{{", ".join(ehr_ids)}}}
"""

    for k, v in filters.items():
        aql += f" AND c/{k} = '{v}'\n"

    if sort:
        aql += f" ORDER BY c/{sort['field']} {sort['order'].upper()}"

    aql += f"\nOFFSET {offset} LIMIT {limit}"

    return aql.strip()


# -------------------- API: Query --------------------
@app.route('/api/query', methods=['POST'])
def run_query():
    params = request.json

    ehr_ids = params.get('ehr_ids', [])
    archetype_id = params.get('archetype_id')
    elements = params.get('elements', [])
    filters = params.get('filters', {})
    limit = params.get('limit', 100)
    offset = params.get('offset', 0)
    sort = params.get('sort')

    # Generate AQL (for frontend display)
    aql_query = generate_aql(
        ehr_ids, archetype_id, elements, filters, limit, offset, sort
    )

    # MongoDB execution
    cursor = collection.find({
        'owner_id.id.value': {'$in': ehr_ids},
        'versions.data.archetype_node_id': archetype_id
    }).skip(offset).limit(limit)

    results = []

    for doc in cursor:
        composition = doc['versions']['data']
        if composition.get('archetype_node_id') != archetype_id:
            continue

        record = {}
        for entry in composition.get('content', []):
            for cluster in entry.get('data', {}).get('items', []):
                extract_values(cluster, record)

        # Field selection
        if elements:
            selected = {}
            for el in elements:
                field = el['field']
                alias = el.get('alias') or field
                selected[alias] = record.get(field)
            record = selected

        # Filters (simple equality)
        if all(record.get(k) == v for k, v in filters.items()):
            results.append(record)

    # Sorting
    if sort:
        results.sort(
            key=lambda x: x.get(sort['field']),
            reverse=(sort['order'] == 'desc')
        )

    return jsonify({
        "aql": aql_query,
        "results": results
    })


if __name__ == '__main__':
    app.run(debug=True)
