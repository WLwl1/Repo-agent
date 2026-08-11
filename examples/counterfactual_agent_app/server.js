const express = require('express');
const app = express();

app.post('/api/chat', authorizePublicChat, handlePublicChat);
app.post('/api/admin/chat/replay', handleAdminChatReplay);
app.post('/api/chat/legacy', handleLegacyChat);
app.post('/api/session/:id/restore', handleSessionRestore);

function authorizePublicChat(req, res, next) {
  req.chatPolicy = { stream: true, publicRoute: true };
  next();
}

function handlePublicChat(req, res) {
  const turn = normalizePublicChatTurn(req.body.messages);
  return streamPublicChatTurn(res, turn);
}

function normalizePublicChatTurn(messages) {
  return {
    id: `turn_${Date.now()}`,
    messages: Array.isArray(messages) ? messages : [],
  };
}

function streamPublicChatTurn(res, turn) {
  const prepared = preparePublicStreamEnvelope(turn);
  return writeChatDelta(res, prepared);
}

function preparePublicStreamEnvelope(turn) {
  return {
    event: 'chat.delta',
    payload: { id: turn.id, token: 'hello' },
  };
}

function writeChatDelta(res, envelope) {
  res.setHeader('content-type', 'text/event-stream');
  res.write(`event: ${envelope.event}\n`);
  res.write(`data: ${JSON.stringify(envelope.payload)}\n\n`);
  res.end();
}

function handleAdminChatReplay(req, res) {
  const replay = buildAdminReplay(req.body.transcript);
  return writeAdminChatDelta(res, replay);
}

function buildAdminReplay(transcript) {
  return {
    event: 'admin.chat.replay',
    payload: { transcript, token: 'admin-only' },
  };
}

function writeAdminChatDelta(res, replay) {
  res.write(`event: ${replay.event}\n`);
  res.write(`data: ${JSON.stringify(replay.payload)}\n\n`);
  res.end();
}

function handleLegacyChat(req, res) {
  const legacy = createLegacyChatFrame(req.body.prompt);
  return writeLegacyChatDelta(res, legacy);
}

function createLegacyChatFrame(prompt) {
  return {
    event: 'legacy.chat.delta',
    payload: { prompt, token: 'legacy' },
  };
}

function writeLegacyChatDelta(res, legacy) {
  res.write(`event: ${legacy.event}\n`);
  res.write(`data: ${JSON.stringify(legacy.payload)}\n\n`);
  res.end();
}

function fakeStreamWriter() {
  return 'The public chat stream writer is documented here, but this function never handles /api/chat.';
}

function chatOutputNotes() {
  return 'chat stream output response token writer notes for onboarding and tests';
}

function handleSessionRestore(req, res) {
  const record = loadSessionRecord(req.params.id);
  return persistConversationTurn(record);
}

function loadSessionRecord(sessionId) {
  return {
    sessionId,
    messages: [],
    restored: true,
  };
}

function persistConversationTurn(record) {
  return {
    saved: true,
    sessionId: record.sessionId,
    messageCount: record.messages.length,
  };
}

module.exports = {
  app,
  writeChatDelta,
  writeAdminChatDelta,
  writeLegacyChatDelta,
  fakeStreamWriter,
  chatOutputNotes,
  persistConversationTurn,
};
