from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient

app = Flask(__name__)
client = MongoClient("mongodb://localhost:27017")
db = client["ehr_db"]
collection = db["ehr"]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/patients', methods=['GET'])
def get_patients():
    ehr_ids = collection.distinct("owner_id.id.value")
    return jsonify(ehr_ids)

@app.route('/api/compositions', methods=['POST'])
def get_compositions():
    ehr_ids = request.json.get('ehr_ids', [])
    pipeline = [
        {'$match': {'owner_id.id.value': {'$in': ehr_ids}}},
        {'$unwind': '$versions.data.content'},
        {'$group': {
            '_id': '$versions.data.content.archetype_node_id',
            'name': {'$first': '$versions.data.content.name.value'}
        }}
    ]
    res = list(collection.aggregate(pipeline))
    return jsonify([{'archetype_id': r['_id'], 'name': r['name']} for r in res])

def extract_fields(node, out_set):
    if node.get('type') == 'ELEMENT':
        out_set.add(node['name']['value'])
    for child in node.get('items', []):
        extract_fields(child, out_set)

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
    fields = set()
    for entry in doc['versions']['data'].get('content', []):
        if entry['archetype_node_id'] == archetype_id:
            for cluster in entry.get('data', {}).get('items', []):
                extract_fields(cluster, fields)
    return jsonify(sorted(fields))

def extract_values(node, out_dict):
    if node.get('type') == 'ELEMENT':
        name = node['name']['value']
        val = node.get('value', {}).get('magnitude') or node.get('value', {}).get('value')
        out_dict[name] = val
    for child in node.get('items', []):
        extract_values(child, out_dict)

@app.route('/api/query', methods=['POST'])
def run_query():
    params = request.json
    ehr_ids = params.get('ehr_ids', [])
    archetype_id = params.get('archetype_id')
    filters = params.get('filters', {})
    limit = params.get('limit', 100)
    offset = params.get('offset', 0)
    sort = params.get('sort')

    cursor = collection.find({
        'owner_id.id.value': {'$in': ehr_ids},
        'versions.data.archetype_node_id': archetype_id
    }).skip(offset).limit(limit)

    results = []
    for doc in cursor:
        entry = next((c for c in doc['versions']['data']['content']
                      if c['archetype_node_id'] == archetype_id), None)
        if not entry:
            continue
        record = {}
        for cluster in entry.get('data', {}).get('items', []):
            extract_values(cluster, record)
        if all(record.get(k) == v for k, v in filters.items()):
            results.append(record)

    if sort:
        results.sort(key=lambda x: x.get(sort['field']), reverse=(sort['order'] == 'desc'))

    return jsonify({'results': results})

if __name__ == '__main__':
    app.run(debug=True)
