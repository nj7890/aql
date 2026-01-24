$(function () {

  $('#runNLPQuery').click(function () {
    const query = $('#nlp-input').val().trim();

    if (!query) {
      alert("Please enter a natural language query.");
      return;
    }

    $.ajax({
      url: '/api/nlp_query',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ query }),

      success: function (res) {
        $('#aql-output').text(res.aql);
        $('#results-output').text(
          JSON.stringify(res.results, null, 2)
        );
      },

      error: function () {
        $('#aql-output').text('-- Error --');
        $('#results-output').text('-- Query failed --');
      }
    });
  });

  $('#clear').click(function () {
    $('#nlp-input').val('');
    $('#aql-output').text('-- AQL will appear here --');
    $('#results-output').text('-- Results will appear here --');
  });

});
