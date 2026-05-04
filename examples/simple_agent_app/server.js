const express = require('express');
const app = express();

app.post('/api/agent', handleAgentRequest);
app.post('/api/chat', handleAgentStreamRequest);
app.post('/api/chat/json', handleAgentRequest);
app.post('/api/session/reset', resetSession);

async function handleAgentRequest(req, res) {
  const result = await createAssistantTurn(req.body || {});
  res.json({ ok: true, result });
}

async function handleAgentStreamRequest(req, res) {
  const result = await createStreamedAssistantTurn(req.body || {});
  res.json({ ok: true, result });
}

async function createAssistantTurn(payload) {
  return { type: 'sync', payload };
}

async function createStreamedAssistantTurn(payload) {
  const stream = { enabled: true, payload };
  return stream;
}

function resetSession(req, res) {
  res.json({ ok: true });
}

module.exports = app;

