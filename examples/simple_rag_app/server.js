const express = require('express');
const multer = require('multer');
const { createRagStore } = require('./lib/rag-store');

const app = express();
const upload = multer({ storage: multer.memoryStorage() });
const ragStore = createRagStore();

app.get('/api/rag/status', (req, res) => {
  res.json({ ok: true, stats: ragStore.getStats() });
});

app.post('/api/rag/upload', upload.array('documents', 6), (req, res) => handleRagUpload(req, res));
app.post('/api/rag/text', (req, res) => handleRagText(req, res));
app.post('/api/rag/reset', (req, res) => {
  ragStore.reset();
  res.json({ ok: true });
});

async function runAgent(message) {
  const context = ragStore.retrieve(message, 4);
  return { message, context };
}

function handleRagUpload(req, res) {
  ragStore.ingestDocument(req.files || []);
  res.json({ ok: true, action: 'upload' });
}

function handleRagText(req, res) {
  ragStore.ingestDocument([{ text: req.body?.text || '' }]);
  res.json({ ok: true, action: 'text' });
}

module.exports = app;

