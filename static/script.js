$(function(){
  $.getJSON('/api/patients', function(data){
    let sel = $('#patients').empty();
    data.forEach(ehr => sel.append(`<option value="${ehr}">${ehr}</option>`));
  });

  $('#patients').on('change', function(){
    let ehr_ids = $(this).val();
    $.ajax({
      url: '/api/compositions',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ ehr_ids }),
      success: function(comps){
        let sel = $('#composition').empty();
        comps.forEach(c =>
          sel.append(`<option value="${c.archetype_id}">${c.name}</option>`)
        );
        loadFields();
      }
    });
  });

  $('#composition').on('change', loadFields);

  function loadFields(){
    let ehr_id = $('#patients').val()[0];
    let arch = $('#composition').val();
    if (!ehr_id || !arch) return;

    $.ajax({
      url: '/api/fields',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ ehr_id, archetype_id: arch }),
      success: function(fields){
        $('#sortField').empty();
        $('#elements').empty();
        fields.forEach(f => $('#sortField').append(`<option>${f}</option>`));
      }
    });
  }

  $('#add-element').click(function(){
    let row = $(`
      <div class="element-row mb-2 d-flex gap-2">
        <select class="form-select form-select-sm field-select"></select>
        <select class="form-select form-select-sm fn-select">
          <option value="">None</option>
          <option>AVG</option>
          <option>SUM</option>
          <option>COUNT</option>
        </select>
        <input class="form-control form-control-sm alias-input" placeholder="Alias" />
        <button class="btn btn-sm btn-danger remove">×</button>
      </div>
    `);

    $('#elements').append(row);
    row.find('.field-select').append($('#sortField option').clone());
  });

  $('#elements').on('click', '.remove', function(){
    $(this).closest('.element-row').remove();
  });

  $('#runQuery').click(function(){
    let ehr_ids = $('#patients').val();
    let arch = $('#composition').val();

    let elements = [];
    $('.element-row').each(function(){
      elements.push({
        field: $(this).find('.field-select').val(),
        fn: $(this).find('.fn-select').val(),
        alias: $(this).find('.alias-input').val()
      });
    });

    let filters = {};
    try {
      filters = JSON.parse($('#filter-json').val() || '{}');
    } catch (e) {
      alert('Invalid filter JSON');
      return;
    }

    let limit = +$('#limit').val();
    let offset = +$('#offset').val();
    let sortField = $('#sortField').val();
    let sortOrder = $('#sortOrder').val();
    let sort = sortField ? { field: sortField, order: sortOrder } : null;

    $.ajax({
      url: '/api/query',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({
        ehr_ids,
        archetype_id: arch,
        elements,
        filters,
        limit,
        offset,
        sort
      }),
      success: function(res){
        // ✅ NEW: show generated AQL
        $('#aql-output').text(res.aql);

        // Existing behavior
        $('#results-output').text(JSON.stringify(res.results, null, 2));
      }
    });
  });
});
