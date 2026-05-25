const repoInput = document.getElementById('repoInput');
const questionInput = document.getElementById('questionInput');
const cacheCount = document.getElementById('cacheCount');
const modelState = document.getElementById('modelState');
const answerBox = document.getElementById('answerBox');
const mapBox = document.getElementById('mapBox');
const hitList = document.getElementById('hitList');
const traceList = document.getElementById('traceList');
const selectionPanel = document.getElementById('selectionPanel');
const reportLink = document.getElementById('reportLink');
const reportFrame = document.getElementById('reportFrame');
const statusText = document.getElementById('statusText');
const buildReportBtn = document.getElementById('buildReportBtn');
const toolActionSelect = document.getElementById('toolActionSelect');
const toolPathInput = document.getElementById('toolPathInput');
const startLineInput = document.getElementById('startLineInput');
const endLineInput = document.getElementById('endLineInput');
const searchInput = document.getElementById('searchInput');
const commandInput = document.getElementById('commandInput');
const toolOutput = document.getElementById('toolOutput');
const toolRunBtn = document.getElementById('toolRunBtn');
const modelModeToggle = document.getElementById('modelModeToggle');
const engineerBtn = document.getElementById('engineerBtn');
const executionModeSelect = document.getElementById('executionModeSelect');
const refreshRunsBtn = document.getElementById('refreshRunsBtn');
const runsBox = document.getElementById('runsBox');

const actionButtons = [
  document.getElementById('askBtn'),
  engineerBtn,
  buildReportBtn,
  toolRunBtn,
].filter(Boolean);

const tabButtons = Array.from(document.querySelectorAll('.tab'));
const tabPanels = Array.from(document.querySelectorAll('.view-panel'));

const STORAGE_KEYS = {
  repo: 'repo-agent.repo',
};

const state = {
  busy: false,
  lastResult: null,
  lastMap: null,
  lastTool: null,
  runs: [],
  selectedHitIndex: 0,
};

document.getElementById('askBtn').addEventListener('click', runAnalysis);
engineerBtn.addEventListener('click', runEngineering);
buildReportBtn.addEventListener('click', generateReport);
toolRunBtn.addEventListener('click', executeToolAction);
toolActionSelect.addEventListener('change', updateToolForm);
toolOutput.addEventListener('click', handleToolOutputClick);
refreshRunsBtn?.addEventListener('click', refreshRuns);
runsBox?.addEventListener('click', handleRunsClick);

tabButtons.forEach((button) => {
  button.addEventListener('click', () => {
    setActiveView(button.dataset.view);
  });
});

boot();

async function boot() {
  updateToolForm();
  const savedRepo = localStorage.getItem(STORAGE_KEYS.repo);
  if (savedRepo) {
    repoInput.value = savedRepo;
  }
  try {
    await refreshHealth();
    await refreshRuns({ silent: true });
  } catch (error) {
    statusText.textContent = '服务不可用';
    answerBox.innerHTML = `<div class="empty-state">无法连接本地服务：${escapeHtml(error.message)}</div>`;
  }
}

async function runAnalysis() {
  await runTask('正在分析...', async () => {
    persistRepo();
    ensureRepoReady();
    const data = await postJSON('/api/ask', buildPayload());
    state.lastResult = data;
    state.selectedHitIndex = 0;
    renderResult();
    await renderMapFromRepo();
    await refreshHealth();
    setActiveView('answer');
    statusText.textContent = data.model_name ? `分析完成，已使用 ${data.model_name}` : '分析完成';
  });
}

async function generateReport() {
  await runTask('正在生成报告...', async () => {
    persistRepo();
    ensureRepoReady();
    const data = await postJSON('/api/report', buildPayload());
    state.lastResult = data;
    state.selectedHitIndex = 0;
    renderResult();
    await renderMapFromRepo();
    await refreshHealth();

    if (data.report_url) {
      reportLink.href = data.report_url;
      reportLink.classList.remove('disabled');
      reportLink.textContent = '打开 HTML 报告';
      reportFrame.src = data.report_url;
    }

    setActiveView('report');
    statusText.textContent = '报告已生成';
  });
}

async function runEngineering() {
  await runTask('实验编辑任务运行中...', async () => {
    persistRepo();
    ensureRepoReady();
    const task = questionInput.value.trim();
    if (!task) {
      throw new Error('请先输入一个明确的小范围编辑任务。');
    }
    const data = await postJSON('/api/engineer', {
      repo: repoInput.value.trim(),
      task,
      max_steps: 6,
      execution_mode: executionModeSelect?.value || 'workspace',
      force_rebuild: false,
    });
    state.lastResult = normalizeEngineeringResult(data);
    state.selectedHitIndex = 0;
    renderResult();
    await renderMapFromRepo();
    await refreshHealth();
    setActiveView('answer');
    statusText.textContent = `实验编辑 ${data.status || 'finished'}: ${data.run_id || ''}`;
  });
}

function normalizeEngineeringResult(data) {
  const changedFiles = Array.isArray(data.changed_files) ? data.changed_files : [];
  const verification = Array.isArray(data.verification) ? data.verification : [];
  const lines = [
    '## Experimental Engineering Run',
    data.answer || `Run ended with status \`${data.status || 'unknown'}\`.`,
    '',
    '## Run',
    `- Run id: \`${data.run_id || ''}\``,
    `- Status: \`${data.status || ''}\``,
    `- Model: \`${data.model || ''}\``,
    `- Execution mode: \`${data.execution_mode || ''}\``,
    `- Run path: \`${data.run_path || ''}\``,
  ];
  if (data.workspace_root) {
    lines.push(`- Workspace: \`${data.workspace_root}\``);
  }
  if (data.applied) {
    lines.push(`- Applied to source: \`yes\``);
  }
  if (data.plan) {
    lines.push('', '## Planner', data.plan);
  }
  if (changedFiles.length) {
    lines.push('', '## Changed Files', ...changedFiles.map((item) => `- \`${item}\``));
  }
  if (verification.length) {
    lines.push(
      '',
      '## Verification',
      ...verification.slice(-5).map((item) => `- \`${item.command || ''}\` -> exit \`${item.exit_code ?? '?'}\``),
    );
  }
  if (data.diff) {
    lines.push('', '## Diff', '```diff', data.diff, '```');
  }
  if (data.review) {
    lines.push('', '## Reviewer', data.review);
  }
  return {
    mode: 'autonomous_engineering',
    query: data.task || '',
    answer: lines.join('\n'),
    trace: data.trace || [],
    hits: [],
    stats: data.stats || {},
    model_name: data.model || '',
    repo_brief: `run=${data.run_id || ''}`,
  };
}

async function refreshRuns(options = {}) {
  try {
    const data = await getJSON('/api/runs?limit=20');
    state.runs = Array.isArray(data.runs) ? data.runs : [];
    renderRuns();
      if (!options.silent) {
      setActiveView('runs');
      statusText.textContent = 'Runs refreshed';
    }
  } catch (error) {
    if (!options.silent) {
      setActiveView('runs');
      runsBox.innerHTML = `<div class="empty-state">Failed to load runs: ${escapeHtml(error.message)}</div>`;
    }
  }
}

function renderRuns() {
  if (!runsBox) {
    return;
  }
  if (!state.runs.length) {
    runsBox.innerHTML = '<div class="empty-state">No engineering runs yet.</div>';
    return;
  }
  runsBox.classList.remove('empty-state');
  runsBox.innerHTML = state.runs.map((run) => `
    <article class="run-card">
      <div class="run-card-top">
        <strong>${escapeHtml(run.run_id || '')}</strong>
        <span>${escapeHtml(run.status || '')}</span>
      </div>
      <small>${escapeHtml(run.execution_mode || 'local')} · ${escapeHtml(run.model || '')}</small>
      <p>${escapeHtml(run.task || '')}</p>
      <div class="tool-actions">
        <button class="secondary" type="button" data-run-action="open" data-run-id="${escapeHtml(run.run_id || '')}">Open</button>
        <button class="secondary" type="button" data-run-action="resume" data-run-id="${escapeHtml(run.run_id || '')}">Resume</button>
        ${run.execution_mode === 'workspace' && !run.applied ? `<button class="secondary" type="button" data-run-action="apply" data-run-id="${escapeHtml(run.run_id || '')}">Apply</button>` : ''}
      </div>
    </article>
  `).join('');
}

async function handleRunsClick(event) {
  const button = event.target.closest('button[data-run-action]');
  if (!button) {
    return;
  }
  const runId = button.dataset.runId;
  const action = button.dataset.runAction;
  if (action === 'open') {
    await openRun(runId);
  } else if (action === 'resume') {
    await resumeRun(runId);
  } else if (action === 'apply') {
    await applyRun(runId);
  }
}

async function openRun(runId) {
  await runTask('Opening run...', async () => {
    const data = await getJSON(`/api/runs/${encodeURIComponent(runId)}`);
    state.lastResult = normalizeEngineeringResult(data);
    renderResult();
    setActiveView('answer');
    statusText.textContent = `Opened run ${runId}`;
  }, 'runs');
}

async function resumeRun(runId) {
  await runTask('Resuming run...', async () => {
    const data = await postJSON('/api/engineer/resume', { run_id: runId, max_steps: 6 });
    state.lastResult = normalizeEngineeringResult(data);
    renderResult();
    await refreshRuns({ silent: true });
    setActiveView('answer');
    statusText.textContent = `Resumed run ${runId}: ${data.status || ''}`;
  }, 'runs');
}

async function applyRun(runId) {
  if (!window.confirm(`Apply workspace changes from ${runId} to the source repository?`)) {
    return;
  }
  await runTask('Applying workspace changes...', async () => {
    const data = await postJSON('/api/runs/apply', { run_id: runId, confirm: true });
    await refreshRuns({ silent: true });
    setActiveView('runs');
    statusText.textContent = `Applied ${data.applied_files?.length || 0} files from ${runId}`;
  }, 'runs');
}

function buildPayload() {
  return {
    repo: repoInput.value.trim(),
    question: questionInput.value.trim(),
    use_model: Boolean(modelModeToggle?.checked),
    force_rebuild: false,
    top_k: 6,
  };
}

function buildToolPayload(action, extra = {}) {
  return {
    repo: repoInput.value.trim(),
    action,
    force_rebuild: false,
    ...extra,
  };
}

async function executeToolAction() {
  const action = toolActionSelect.value;
  if (action === 'startup') {
    await runToolAction('startup', {}, '正在获取启动提示...');
    return;
  }
  if (action === 'verify') {
    await runToolAction(
      'verify',
      { query: questionInput.value.trim() || '帮我检查这个项目现在能不能用' },
      '正在做快速验证...',
    );
    return;
  }
  if (action === 'list') {
    await runToolAction(
      'list',
      { path: toolPathInput.value.trim() || '.', limit: 60 },
      '正在读取目录...',
    );
    return;
  }
  if (action === 'read') {
    const relpath = toolPathInput.value.trim();
    if (!relpath) {
      showToolValidation('请先输入文件路径');
      return;
    }
    await runToolAction(
      'read',
      {
        path: relpath,
        start_line: Number(startLineInput.value || 1),
        end_line: Number(endLineInput.value || 120),
      },
      '正在读取文件...',
    );
    return;
  }
  if (action === 'search') {
    const terms = parseSearchTerms(searchInput.value);
    if (!terms.length) {
      showToolValidation('请先输入搜索词');
      return;
    }
    await runToolAction(
      'search',
      { terms, limit: 20 },
      '正在搜索文本...',
    );
    return;
  }
  if (action === 'run') {
    const command = commandInput.value.trim();
    if (!command) {
      showToolValidation('请先输入命令');
      return;
    }
    await runToolAction(
      'run',
      {
        command,
        timeout_seconds: 45,
      },
      '正在执行命令...',
    );
  }
}

async function runToolAction(action, payload, message) {
  await runTask(message, async () => {
    persistRepo();
    ensureRepoReady();
    const data = await postJSON('/api/tools', buildToolPayload(action, payload));
    state.lastTool = data;
    renderToolResult(data);
    await refreshHealth();
    setActiveView('tools');
    statusText.textContent = toolStatusText(action, data);
  }, 'tools');
}

function updateToolForm() {
  const action = toolActionSelect.value;
  const showPath = action === 'list' || action === 'read';
  const showLines = action === 'read';
  const showSearch = action === 'search';
  const showCommand = action === 'run';

  toolPathInput.hidden = !showPath;
  startLineInput.hidden = !showLines;
  endLineInput.hidden = !showLines;
  searchInput.hidden = !showSearch;
  commandInput.hidden = !showCommand;

  toolPathInput.disabled = !showPath;
  startLineInput.disabled = !showLines;
  endLineInput.disabled = !showLines;
  searchInput.disabled = !showSearch;
  commandInput.disabled = !showCommand;

  if (action === 'list' && !toolPathInput.value.trim()) {
    toolPathInput.value = '.';
  }
  if (action === 'startup') {
    toolRunBtn.textContent = '查看';
  } else if (action === 'verify') {
    toolRunBtn.textContent = '检查';
  } else {
    toolRunBtn.textContent = '执行';
  }
}

async function renderMapFromRepo() {
  const repo = repoInput.value.trim();
  if (!repo) {
    state.lastMap = null;
    renderMap();
    return;
  }
  state.lastMap = await getJSON(`/api/map?repo=${encodeURIComponent(repo)}`);
  renderMap();
}

function renderResult() {
  const data = state.lastResult;
  if (!data) {
    answerBox.innerHTML = '<div class="empty-state">点击“分析”后，这里会展示最终结论。</div>';
    hitList.innerHTML = '<div class="empty-state">还没有证据结果。</div>';
    traceList.innerHTML = '<div class="empty-state">暂无执行轨迹。</div>';
    selectionPanel.innerHTML = '<div class="empty-state">点击证据卡片查看细节。</div>';
    return;
  }

  answerBox.classList.remove('empty-state');
  answerBox.innerHTML = `${renderDiagnostics(data.diagnostics)}${renderMarkdown(data.answer || '暂无结果')}`;

  renderEvidence(data.hits || []);
  renderTrace(data.trace || []);
  renderSelection();
}

function renderDiagnostics(diagnostics) {
  if (!diagnostics || !diagnostics.label) {
    return '';
  }
  const warnings = Array.isArray(diagnostics.warnings) ? diagnostics.warnings : [];
  const strengths = Array.isArray(diagnostics.strengths) ? diagnostics.strengths : [];
  const notes = warnings.length ? warnings : strengths.slice(0, 2);
  return `
    <section class="diagnostics-strip">
      <article>
        <span>置信度</span>
        <strong>${escapeHtml(diagnostics.label)} · ${Number(diagnostics.confidence || 0).toFixed(2)}</strong>
      </article>
      <article>
        <span>证据覆盖</span>
        <strong>${Number(diagnostics.evidence_count || 0)} 条 · ${Number(diagnostics.unique_files || 0)} 文件</strong>
      </article>
      <article>
        <span>图支撑</span>
        <strong>${Number(diagnostics.graph_edge_count || 0)} 条边</strong>
      </article>
      <article>
        <span>提示</span>
        <strong>${escapeHtml(notes.join('；') || '无明显风险')}</strong>
      </article>
    </section>
  `;
}

function renderEvidence(hits) {
  hitList.replaceChildren();
  if (!hits.length) {
    hitList.innerHTML = '<div class="empty-state">还没有证据结果。</div>';
    return;
  }

  const cards = hits.map((hit, index) => {
    const card = document.createElement('article');
    card.className = `hit-card${index === state.selectedHitIndex ? ' is-selected' : ''}`;
    card.innerHTML = `
      <div class="hit-title">${escapeHtml(hit.source_label)}</div>
      <div class="hit-meta">${escapeHtml(hit.relpath)} · ${hit.start_line}-${hit.end_line} · ${Number(hit.score).toFixed(2)}</div>
      <div class="pill-list">
        ${(hit.reasons || []).slice(0, 3).map((reason) => `<span class="pill reason">${escapeHtml(reason)}</span>`).join('')}
        ${(hit.matched_terms || []).slice(0, 3).map((term) => `<span class="pill">${escapeHtml(term)}</span>`).join('')}
      </div>
      <pre class="snippet">${escapeHtml(trimSnippet(hit.snippet || ''))}</pre>
    `;
    card.addEventListener('click', () => {
      state.selectedHitIndex = index;
      renderEvidence(hits);
      renderSelection();
    });
    return card;
  });

  hitList.replaceChildren(...cards);
}

function renderTrace(trace) {
  traceList.replaceChildren();
  if (!trace.length) {
    traceList.innerHTML = '<div class="empty-state">暂无执行轨迹。</div>';
    return;
  }

  const cards = trace.map((item) => {
    const card = document.createElement('article');
    card.className = 'trace-card';
    card.innerHTML = `
      <div class="trace-top">
        <span class="trace-step">${item.step ?? '?'}</span>
        <span class="trace-type">${escapeHtml(item.type || 'trace')}</span>
      </div>
      <pre>${escapeHtml(String(item.content || ''))}</pre>
    `;
    return card;
  });

  traceList.replaceChildren(...cards);
}

function renderSelection() {
  const hits = state.lastResult?.hits || [];
  const hit = hits[state.selectedHitIndex];
  if (!hit) {
    selectionPanel.innerHTML = '<div class="empty-state">点击证据卡片查看细节。</div>';
    return;
  }

  selectionPanel.classList.remove('empty-state');
  selectionPanel.innerHTML = `
    <div class="hit-title">${escapeHtml(hit.source_label)}</div>
    <div class="selection-meta">${escapeHtml(hit.relpath)} · ${hit.start_line}-${hit.end_line} · ${hit.symbol_kind || 'file'}</div>
    <div class="pill-list">
      ${(hit.reasons || []).slice(0, 4).map((reason) => `<span class="pill reason">${escapeHtml(reason)}</span>`).join('')}
      ${(hit.matched_terms || []).slice(0, 4).map((term) => `<span class="pill">${escapeHtml(term)}</span>`).join('')}
    </div>
    <pre class="selection-code">${escapeHtml(hit.snippet || '')}</pre>
  `;
}

function renderMap() {
  const data = state.lastMap;
  if (!data) {
    mapBox.innerHTML = '<div class="empty-state">还没有仓库快照。</div>';
    return;
  }

  const stats = data.stats || {};
  const topFiles = Array.isArray(data.top_files) ? data.top_files : [];
  const topEdges = Array.isArray(data.top_edges) ? data.top_edges : [];
  const memory = data.memory || {};

  mapBox.classList.remove('empty-state');
  mapBox.innerHTML = `
    <section class="map-section">
      <h3>概览</h3>
      <div class="map-list">
        <article class="map-item"><strong>文件数</strong><small>${stats.file_count ?? '--'}</small></article>
        <article class="map-item"><strong>Chunks</strong><small>${stats.chunk_count ?? '--'}</small></article>
        <article class="map-item"><strong>边数</strong><small>${stats.graph_edge_count ?? '--'}</small></article>
      </div>
      ${memory.brief ? `<pre class="snippet">${escapeHtml(memory.brief)}</pre>` : ''}
    </section>
    <section class="map-section">
      <h3>重点文件</h3>
      <div class="map-list">
        ${topFiles.slice(0, 6).map((file) => `
          <article class="map-item">
            <strong>${escapeHtml(file.relpath)}</strong>
            <small>${escapeHtml(file.language)} · 行数 ${file.line_count} · 符号 ${file.symbol_count}${file.roles?.length ? ` · ${escapeHtml(file.roles.join(', '))}` : ''}</small>
          </article>
        `).join('') || '<div class="empty-state">暂无重点文件。</div>'}
      </div>
    </section>
    <section class="map-section">
      <h3>关键关系</h3>
      <div class="map-list">
        ${topEdges.slice(0, 6).map((edge) => `
          <article class="map-item">
            <strong>${escapeHtml(edge.label)}</strong>
            <small>${escapeHtml(edge.source)} → ${escapeHtml(edge.target)}</small>
          </article>
        `).join('') || '<div class="empty-state">暂无关键关系。</div>'}
      </div>
    </section>
  `;
}

function renderToolResult(data) {
  if (!data) {
    toolOutput.innerHTML = '<div class="empty-state">这里会展示目录、文件、启动提示和命令输出。</div>';
    return;
  }

  if (data.action === 'startup') {
    renderStartupResult(data);
    return;
  }
  if (data.action === 'list') {
    renderDirectoryResult(data);
    return;
  }
  if (data.action === 'read') {
    renderReadResult(data);
    return;
  }
  if (data.action === 'search') {
    renderSearchResult(data);
    return;
  }
  if (data.action === 'run' || data.action === 'verify') {
    renderCommandResult(data);
    return;
  }

  toolOutput.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

function renderStartupResult(data) {
  const commands = Array.isArray(data.commands) ? data.commands : [];
  const verifyBlock = data.verify_command
    ? `
      <article class="tool-card">
        <strong>推荐验证命令</strong>
        <small>${escapeHtml(data.verify_command)}</small>
        <div class="tool-actions">
          <button class="secondary" type="button" data-command="${escapeHtml(data.verify_command)}">填入命令</button>
        </div>
      </article>
    `
    : '';

  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>启动建议</strong>
      <small>${escapeHtml(data.repo_root || '')}</small>
    </div>
    ${commands.map((item) => `
      <article class="tool-card">
        <span class="tool-card-title">${escapeHtml(item.label || item.command)}</span>
        <small>${escapeHtml(item.reason || '')}</small>
        <pre class="tool-code">${escapeHtml(item.command || '')}</pre>
        <div class="tool-actions">
          <button class="secondary" type="button" data-command="${escapeHtml(item.command || '')}">填入命令</button>
        </div>
      </article>
    `).join('') || '<div class="empty-state">没有推断出启动命令。</div>'}
    ${verifyBlock}
  `;
}

function renderDirectoryResult(data) {
  const entries = Array.isArray(data.entries) ? data.entries : [];
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>目录</strong>
      <small>${escapeHtml(data.path || '.')}</small>
    </div>
    ${entries.map((entry) => `
      <article class="tool-card">
        <span class="tool-card-title">${escapeHtml(entry.name)}</span>
        <small>${escapeHtml(entry.kind)} · ${escapeHtml(entry.relpath)}${entry.kind === 'file' ? ` · ${entry.size} bytes` : ''}</small>
        <div class="tool-actions">
          <button
            class="secondary"
            type="button"
            data-open-path="${escapeHtml(entry.relpath)}"
            data-open-kind="${escapeHtml(entry.kind)}"
          >打开</button>
        </div>
      </article>
    `).join('') || '<div class="empty-state">目录为空。</div>'}
  `;
}

function renderReadResult(data) {
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>${escapeHtml(data.relpath || '')}</strong>
      <small>${data.start_line ?? 1}-${data.end_line ?? 1} · 共 ${data.line_count ?? 0} 行</small>
      <pre class="tool-code">${escapeHtml(data.content || '')}</pre>
    </div>
  `;
}

function renderSearchResult(data) {
  const matches = Array.isArray(data.matches) ? data.matches : [];
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>文本搜索</strong>
      <small>${escapeHtml((data.terms || []).join(', '))}</small>
    </div>
    ${matches.map((match) => `
      <article class="tool-card">
        <span class="tool-card-title">${escapeHtml(match.relpath)}:${match.line_number}</span>
        <small>${escapeHtml((match.matched_terms || []).join(', '))}</small>
        <pre class="tool-code">${escapeHtml(match.line_text || '')}</pre>
        <div class="tool-actions">
          <button
            class="secondary"
            type="button"
            data-open-path="${escapeHtml(match.relpath)}"
            data-open-kind="file"
            data-open-line="${Number(match.line_number || 1)}"
          >打开到这里</button>
        </div>
      </article>
    `).join('') || '<div class="empty-state">没有搜到结果。</div>'}
  `;
}

function renderCommandResult(data) {
  const supported = data.supported !== false;
  if (!supported) {
    toolOutput.innerHTML = `<div class="empty-state">${escapeHtml(data.message || '当前仓库没有可推断的验证命令。')}</div>`;
    return;
  }
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>${escapeHtml(data.command || '')}</strong>
      <small>cwd: ${escapeHtml(data.cwd || '')} · exit code: ${data.exit_code ?? '--'}</small>
      ${data.stdout ? `<pre class="tool-code">${escapeHtml(data.stdout)}</pre>` : ''}
      ${data.stderr ? `<pre class="tool-code">${escapeHtml(data.stderr)}</pre>` : ''}
    </div>
  `;
}

async function handleToolOutputClick(event) {
  const button = event.target.closest('button');
  if (!button) {
    return;
  }
  if (button.dataset.command) {
    toolActionSelect.value = 'run';
    updateToolForm();
    commandInput.value = button.dataset.command;
    commandInput.focus();
    return;
  }
  if (!button.dataset.openPath) {
    return;
  }

  const relpath = button.dataset.openPath;
  const kind = button.dataset.openKind || 'file';
  toolPathInput.value = relpath;
  if (kind === 'dir') {
    toolActionSelect.value = 'list';
    updateToolForm();
    await executeToolAction();
    return;
  }
  const lineNumber = Number(button.dataset.openLine || 1);
  toolActionSelect.value = 'read';
  updateToolForm();
  startLineInput.value = Math.max(1, lineNumber - 4);
  endLineInput.value = Math.max(Number(startLineInput.value) + 20, lineNumber + 12);
  await executeToolAction();
}

function setActiveView(viewName) {
  tabButtons.forEach((button) => {
    button.classList.toggle('is-active', button.dataset.view === viewName);
  });
  tabPanels.forEach((panel) => {
    panel.classList.toggle('is-active', panel.id === `view-${viewName}`);
  });
}

function ensureRepoReady() {
  if (!repoInput.value.trim()) {
    throw new Error('请先输入仓库路径');
  }
}

function persistRepo() {
  localStorage.setItem(STORAGE_KEYS.repo, repoInput.value.trim());
}

async function refreshHealth() {
  const health = await getJSON('/api/health');
  cacheCount.textContent = health.cached_indexes ?? 0;
  modelState.textContent = health.llm_available ? `已接入 ${health.model}` : '未接模型';
}

async function runTask(message, task, failureView = 'answer') {
  if (state.busy) {
    return;
  }
  state.busy = true;
  statusText.textContent = message;
  actionButtons.forEach((button) => { button.disabled = true; });
  try {
    await task();
  } catch (error) {
    statusText.textContent = '执行失败';
    setActiveView(failureView);
    if (failureView === 'tools') {
      toolOutput.innerHTML = `<div class="empty-state">执行失败：${escapeHtml(error.message)}</div>`;
    } else {
      answerBox.innerHTML = `<div class="empty-state">执行失败：${escapeHtml(error.message)}</div>`;
    }
  } finally {
    state.busy = false;
    actionButtons.forEach((button) => { button.disabled = false; });
  }
}

async function getJSON(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || '请求失败');
  }
  return data;
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || '请求失败');
  }
  return data;
}

function trimSnippet(text) {
  const lines = String(text).split('\n');
  return lines.length <= 12 ? text : `${lines.slice(0, 12).join('\n')}\n...`;
}

function parseSearchTerms(value) {
  return String(value || '')
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function toolStatusText(action, data) {
  if (action === 'verify') {
    return data.supported === false ? '当前仓库没有可推断的验证命令' : '验证完成';
  }
  if (action === 'run') {
    return '命令执行完成';
  }
  if (action === 'startup') {
    return '启动提示已更新';
  }
  if (action === 'read') {
    return '文件读取完成';
  }
  if (action === 'search') {
    return '文本搜索完成';
  }
  if (action === 'list') {
    return '目录读取完成';
  }
  return '工具执行完成';
}

function showToolValidation(message) {
  setActiveView('tools');
  statusText.textContent = message;
  toolOutput.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderMarkdown(source) {
  const text = String(source || '').replace(/\r\n?/g, '\n').trim();
  if (!text) {
    return '<div class="empty-state">暂无结果。</div>';
  }

  const lines = text.split('\n');
  const html = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith('```')) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      html.push(`<pre>${escapeHtml(codeLines.join('\n'))}</pre>`);
      continue;
    }

    if (/^##\s+/.test(trimmed)) {
      html.push(`<h2>${renderInline(trimmed.replace(/^##\s+/, ''))}</h2>`);
      index += 1;
      continue;
    }

    if (/^###\s+/.test(trimmed)) {
      html.push(`<h3>${renderInline(trimmed.replace(/^###\s+/, ''))}</h3>`);
      index += 1;
      continue;
    }

    if (/^-\s+/.test(trimmed)) {
      const items = [];
      while (index < lines.length && /^-\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^-\s+/, ''));
        index += 1;
      }
      html.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join('')}</ul>`);
      continue;
    }

    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^##\s+/.test(lines[index].trim()) &&
      !/^###\s+/.test(lines[index].trim()) &&
      !/^-\s+/.test(lines[index].trim()) &&
      !lines[index].trim().startsWith('```')
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    html.push(`<p>${renderInline(paragraph.join(' '))}</p>`);
  }

  return html.join('');
}

function renderInline(text) {
  return escapeHtml(String(text || ''))
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
