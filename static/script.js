$(function () {

  $('#runNLPQuery').click(sendQuery);
  $('#nlp-input').keypress(function (e) {
    if (e.which === 13) sendQuery();
  });

  function scrollBottom() {
    const chat = $('#chat-window')[0];
    chat.scrollTop = chat.scrollHeight;
  }

  function userMessage(text) {
    $('#chat-window').append(`
      <div class="msg user-msg">
        <div class="label">You</div>
        <div class="content">${text}</div>
      </div>
    `);
    scrollBottom();
  }

  function assistantThinking(id) {
    $('#chat-window').append(`
      <div class="msg assistant-msg" id="${id}">
        <div class="label">EHR-Asst</div>
        <div class="content thinking">Interpreting query…</div>
      </div>
    `);
    scrollBottom();
  }

  function assistantResponse(steps, answer, aql, metrics) {
    const stepsHtml = steps.map(s => `<li>${s}</li>`).join('');

    $('#chat-window').append(`
      <div class="msg assistant-msg">
        <div class="label">EHR-Asst</div>
        <div class="content">

          <div class="interpretation">
            <strong>My interpretation is:</strong>
            <ul>${stepsHtml}</ul>
          </div>

          <div class="answer">
            <strong>Answer:</strong>
            <pre>${answer}</pre>
          </div>

          <div class="aql-block">
            <strong>Generated AQL:</strong>
            <pre>${aql}</pre>
          </div>

          <div class="metrics-block">
            <strong>Evaluation Metrics:</strong>
            <ul>
              <li>Field Mapping Accuracy: ${metrics.field_mapping_accuracy}</li>
              <li>Condition Extraction Accuracy: ${metrics.condition_extraction_accuracy}</li>
              <li>Query Success: ${metrics.query_success}</li>
              <li>Latency (ms): ${metrics.latency_ms}</li>
            </ul>
          </div>

        </div>
      </div>
    `);
    scrollBottom();
  }

  function sendQuery() {
    const query = $('#nlp-input').val().trim();
    if (!query) return;

    userMessage(query);
    $('#nlp-input').val('');

    const thinkingId = `thinking-${Date.now()}`;
    assistantThinking(thinkingId);

    $.ajax({
      url: '/api/nlp_query',
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ query }),

      success: function (res) {
        $('#' + thinkingId).remove();

        const steps = [];

        res.context.select_fields.forEach(f =>
          steps.push(`Fetch "${f}" from EHR`)
        );

        Object.entries(res.context.filters).forEach(([f, conds]) => {
          conds.forEach(([op, val]) =>
            steps.push(`Filter "${f}" ${op} ${val}`)
          );
        });

        steps.push(`Limit results to ${res.context.limit}`);

        const answer =
          res.results.length === 0
            ? "No matching records found."
            : JSON.stringify(res.results, null, 2);

        assistantResponse(
          steps,
          answer,
          res.aql,
          res.metrics
        );
      },

      error: function () {
        $('#' + thinkingId).remove();
        assistantResponse(
          ["Unable to interpret the query"],
          "No answer available.",
          "--",
          {}
        );
      }
    });
  }

  $('#clear').click(function () {
    $.post('/api/reset_context');
    $('#chat-window').html(`
      <div class="assistant-intro">
        <strong>EHR-Asst</strong><br>
        Conversation reset. Start a new query.
      </div>
    `);
  });

});
