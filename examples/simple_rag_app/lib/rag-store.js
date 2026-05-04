function createRagStore() {
  const documents = [];

  return {
    getStats,
    retrieve,
    ingestDocument,
    reset,
  };

  function getStats() {
    return { documentCount: documents.length };
  }

  function retrieve(query, topK) {
    return { query, topK, hits: documents.slice(0, topK) };
  }

  function ingestDocument(items) {
    documents.push(...items);
    return { ok: true };
  }

  function reset() {
    documents.length = 0;
  }
}

module.exports = { createRagStore };

