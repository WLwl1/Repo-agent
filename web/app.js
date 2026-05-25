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
const langZhBtn = document.getElementById('langZhBtn');
const langEnBtn = document.getElementById('langEnBtn');

const actionButtons = [
  document.getElementById('askBtn'),
  engineerBtn,
  buildReportBtn,
  toolRunBtn,
].filter(Boolean);

const tabButtons = Array.from(document.querySelectorAll('.tab'));
const tabPanels = Array.from(document.querySelectorAll('.view-panel'));
const toolActionOptions = Array.from(toolActionSelect.options);

const STORAGE_KEYS = {
  repo: 'repo-agent.repo',
  language: 'repo-agent.language',
};

const state = {
  busy: false,
  language: 'zh',
  lastResult: null,
  lastMap: null,
  lastTool: null,
  runs: [],
  selectedHitIndex: 0,
};

const I18N = {
  zh: {
    statusUnavailable: '服务不可用',
    statusAnalyzing: '正在分析...',
    statusAnalysisDone: '分析完成',
    statusAnalysisDoneModel: (model) => `分析完成，已使用 ${model}`,
    statusReportBuilding: '正在生成报告...',
    statusReportDone: '报告已生成',
    statusEngineering: '实验编辑任务运行中...',
    statusEngineeringDone: (status, runId) => `实验编辑 ${status || 'finished'}: ${runId || ''}`,
    statusRunsRefreshed: 'Runs refreshed',
    statusOpenedRun: (runId) => `Opened run ${runId}`,
    statusResumedRun: (runId, status) => `Resumed run ${runId}: ${status || ''}`,
    statusAppliedRun: (count, runId) => `Applied ${count || 0} files from ${runId}`,
    statusApplying: 'Applying workspace changes...',
    statusOpeningRun: 'Opening run...',
    statusResumingRun: 'Resuming run...',
    statusToolStartup: '正在获取启动提示...',
    statusToolVerify: '正在做快速验证...',
    statusToolList: '正在读取目录...',
    statusToolRead: '正在读取文件...',
    statusToolSearch: '正在搜索文本...',
    statusToolRun: '正在执行命令...',
    statusFailed: '执行失败',
    statusLanguage: '已切换为中文',
    sidebarTabs: ['结论', '证据', '仓库', '工具', 'Runs', '报告'],
    cacheLabel: '缓存索引',
    modelLabel: '模型状态',
    modelChecking: '检测中',
    modelNone: '未接模型',
    modelReady: (model) => `已接入 ${model}`,
    eyebrow: 'Repository Investigation',
    title: '仓库证据工作台',
    repoLabel: '仓库路径',
    repoPlaceholder: '输入仓库路径，例如 C:\\project\\my-repo',
    questionLabel: '调查问题或编辑任务',
    questionPlaceholder: '先问清楚：问题在哪、证据是什么、下一步该看哪里',
    ask: '调查',
    engineer: '实验编辑',
    workspace: '工作区沙箱',
    local: '直接改源仓库',
    aiMode: 'AI 增强',
    answerTitle: '结论',
    answerSubtitle: '最终回答、关键证据和定位建议',
    evidenceTitle: '证据',
    evidenceSubtitle: '按相关性排序的文件、符号和片段',
    mapTitle: '仓库快照',
    mapSubtitle: '索引统计、重点文件和关键关系',
    toolsTitle: '工具',
    toolsSubtitle: '安全读取、搜索和验证命令',
    runsTitle: 'Runs',
    runsSubtitle: '工程模式运行记录、恢复和应用',
    refresh: '刷新',
    reportTitle: '报告',
    reportSubtitle: '生成可分享的 HTML 调查报告',
    buildReport: '生成报告',
    reportPending: '尚未生成',
    reportOpen: '打开 HTML 报告',
    selectedEvidence: '选中证据',
    traceTitle: '执行轨迹',
    answerEmpty: '点击“调查”后，这里会展示结论、证据和可追踪路径。',
    answerEmptyShort: '点击“调查”后，这里会展示最终结论。',
    evidenceEmpty: '还没有证据结果。',
    traceEmpty: '暂无执行轨迹。',
    selectionEmpty: '点击证据卡片查看细节。',
    mapEmpty: '还没有仓库快照。',
    toolEmpty: '这里会展示目录、文件、启动提示和命令输出。',
    runsEmpty: 'No engineering runs yet.',
    runsLoadEmpty: 'No runs loaded.',
    toolOptions: ['启动提示', '检查项目', '列目录', '读文件', '搜文本', '跑命令'],
    toolPathPlaceholder: '路径，例如 web/app.js 或 .',
    startLinePlaceholder: '起始行',
    endLinePlaceholder: '结束行',
    searchPlaceholder: '关键词，例如 chat, stream, render',
    commandPlaceholder: '命令，例如 python -m repo_agent eval',
    toolView: '查看',
    toolCheck: '检查',
    toolExecute: '执行',
    needRepo: '请先输入仓库路径',
    needTask: '请先输入一个明确的小范围编辑任务。',
    needFile: '请先输入文件路径',
    needSearch: '请先输入搜索词',
    needCommand: '请先输入命令',
    defaultVerifyQuery: '帮我检查这个项目现在能不能用',
    diagnosticsConfidence: '置信度',
    diagnosticsCoverage: '证据覆盖',
    diagnosticsGraph: '图支撑',
    diagnosticsNote: '提示',
    diagnosticsFiles: (hits, files) => `${hits} 条 · ${files} 文件`,
    diagnosticsEdges: (edges) => `${edges} 条边`,
    diagnosticsNone: '无明显风险',
    overview: '概览',
    fileCount: '文件数',
    chunks: 'Chunks',
    edgeCount: '边数',
    topFiles: '重点文件',
    lineCount: '行数',
    symbols: '符号',
    keyRelations: '关键关系',
    noTopFiles: '暂无重点文件。',
    noKeyRelations: '暂无关键关系。',
    startupTitle: '启动建议',
    verifyCommand: '推荐验证命令',
    fillCommand: '填入命令',
    noStartup: '没有推断出启动命令。',
    directory: '目录',
    emptyDirectory: '目录为空。',
    open: '打开',
    openHere: '打开到这里',
    textSearch: '文本搜索',
    noSearch: '没有搜到结果。',
    noVerify: '当前仓库没有可推断的验证命令。',
    totalLines: (count) => `共 ${count || 0} 行`,
    cwdExit: (cwd, code) => `cwd: ${cwd || ''} · exit code: ${code ?? '--'}`,
    toolDone: {
      verify: '验证完成',
      run: '命令执行完成',
      startup: '启动提示已更新',
      read: '文件读取完成',
      search: '文本搜索完成',
      list: '目录读取完成',
      default: '工具执行完成',
      unsupportedVerify: '当前仓库没有可推断的验证命令',
    },
    failPrefix: '执行失败：',
    lineMeta: (relpath, start, end, kind) => `${relpath} · ${start}-${end} · ${kind}`,
  },
  en: {
    statusUnavailable: 'Service unavailable',
    statusAnalyzing: 'Analyzing...',
    statusAnalysisDone: 'Analysis complete',
    statusAnalysisDoneModel: (model) => `Analysis complete with ${model}`,
    statusReportBuilding: 'Generating report...',
    statusReportDone: 'Report generated',
    statusEngineering: 'Experimental engineering task running...',
    statusEngineeringDone: (status, runId) => `Engineering ${status || 'finished'}: ${runId || ''}`,
    statusRunsRefreshed: 'Runs refreshed',
    statusOpenedRun: (runId) => `Opened run ${runId}`,
    statusResumedRun: (runId, status) => `Resumed run ${runId}: ${status || ''}`,
    statusAppliedRun: (count, runId) => `Applied ${count || 0} files from ${runId}`,
    statusApplying: 'Applying workspace changes...',
    statusOpeningRun: 'Opening run...',
    statusResumingRun: 'Resuming run...',
    statusToolStartup: 'Loading startup hints...',
    statusToolVerify: 'Running quick verification...',
    statusToolList: 'Reading directory...',
    statusToolRead: 'Reading file...',
    statusToolSearch: 'Searching text...',
    statusToolRun: 'Running command...',
    statusFailed: 'Failed',
    statusLanguage: 'Switched to English',
    sidebarTabs: ['Answer', 'Evidence', 'Repository', 'Tools', 'Runs', 'Report'],
    cacheLabel: 'Cached Indexes',
    modelLabel: 'Model',
    modelChecking: 'Checking',
    modelNone: 'Not configured',
    modelReady: (model) => `Connected: ${model}`,
    eyebrow: 'Repository Investigation',
    title: 'Repository Evidence Studio',
    repoLabel: 'Repository Path',
    repoPlaceholder: 'Enter a repository path, for example C:\\project\\my-repo',
    questionLabel: 'Investigation Question Or Edit Task',
    questionPlaceholder: 'Ask first: where is the issue, what is the evidence, what should I inspect next?',
    ask: 'Investigate',
    engineer: 'Experimental Edit',
    workspace: 'Workspace Sandbox',
    local: 'Edit Source Repo',
    aiMode: 'AI Enhanced',
    answerTitle: 'Answer',
    answerSubtitle: 'Final answer, key evidence, and localization guidance',
    evidenceTitle: 'Evidence',
    evidenceSubtitle: 'Ranked files, symbols, and snippets',
    mapTitle: 'Repository Snapshot',
    mapSubtitle: 'Index stats, important files, and key relationships',
    toolsTitle: 'Tools',
    toolsSubtitle: 'Safe reads, search, and verification commands',
    runsTitle: 'Runs',
    runsSubtitle: 'Engineering run history, resume, and apply',
    refresh: 'Refresh',
    reportTitle: 'Report',
    reportSubtitle: 'Generate a shareable HTML investigation report',
    buildReport: 'Generate Report',
    reportPending: 'Not generated',
    reportOpen: 'Open HTML Report',
    selectedEvidence: 'Selected Evidence',
    traceTitle: 'Trace',
    answerEmpty: 'Click "Investigate" to see the conclusion, evidence, and trace.',
    answerEmptyShort: 'Click "Investigate" to see the final answer.',
    evidenceEmpty: 'No evidence yet.',
    traceEmpty: 'No trace yet.',
    selectionEmpty: 'Click an evidence card to inspect details.',
    mapEmpty: 'No repository snapshot yet.',
    toolEmpty: 'Directory listings, files, startup hints, and command output appear here.',
    runsEmpty: 'No engineering runs yet.',
    runsLoadEmpty: 'No runs loaded.',
    toolOptions: ['Startup Hints', 'Verify Project', 'List Directory', 'Read File', 'Search Text', 'Run Command'],
    toolPathPlaceholder: 'Path, for example web/app.js or .',
    startLinePlaceholder: 'Start line',
    endLinePlaceholder: 'End line',
    searchPlaceholder: 'Terms, for example chat, stream, render',
    commandPlaceholder: 'Command, for example python -m repo_agent eval',
    toolView: 'View',
    toolCheck: 'Check',
    toolExecute: 'Run',
    needRepo: 'Enter a repository path first',
    needTask: 'Enter a clear, small-scope edit task first.',
    needFile: 'Enter a file path first',
    needSearch: 'Enter search terms first',
    needCommand: 'Enter a command first',
    defaultVerifyQuery: 'Check whether this project still works',
    diagnosticsConfidence: 'Confidence',
    diagnosticsCoverage: 'Evidence Coverage',
    diagnosticsGraph: 'Graph Support',
    diagnosticsNote: 'Note',
    diagnosticsFiles: (hits, files) => `${hits} hits · ${files} files`,
    diagnosticsEdges: (edges) => `${edges} edges`,
    diagnosticsNone: 'No obvious risk',
    overview: 'Overview',
    fileCount: 'Files',
    chunks: 'Chunks',
    edgeCount: 'Edges',
    topFiles: 'Important Files',
    lineCount: 'lines',
    symbols: 'symbols',
    keyRelations: 'Key Relationships',
    noTopFiles: 'No important files yet.',
    noKeyRelations: 'No key relationships yet.',
    startupTitle: 'Startup Hints',
    verifyCommand: 'Recommended Verification Command',
    fillCommand: 'Use Command',
    noStartup: 'No startup command inferred.',
    directory: 'Directory',
    emptyDirectory: 'Directory is empty.',
    open: 'Open',
    openHere: 'Open here',
    textSearch: 'Text Search',
    noSearch: 'No matches found.',
    noVerify: 'No verification command could be inferred for this repository.',
    totalLines: (count) => `${count || 0} total lines`,
    cwdExit: (cwd, code) => `cwd: ${cwd || ''} · exit code: ${code ?? '--'}`,
    toolDone: {
      verify: 'Verification complete',
      run: 'Command complete',
      startup: 'Startup hints updated',
      read: 'File read complete',
      search: 'Text search complete',
      list: 'Directory read complete',
      default: 'Tool complete',
      unsupportedVerify: 'No verification command could be inferred',
    },
    failPrefix: 'Failed: ',
    lineMeta: (relpath, start, end, kind) => `${relpath} · ${start}-${end} · ${kind}`,
  },
};

document.getElementById('askBtn').addEventListener('click', runAnalysis);
engineerBtn.addEventListener('click', runEngineering);
buildReportBtn.addEventListener('click', generateReport);
toolRunBtn.addEventListener('click', executeToolAction);
toolActionSelect.addEventListener('change', updateToolForm);
toolOutput.addEventListener('click', handleToolOutputClick);
refreshRunsBtn?.addEventListener('click', refreshRuns);
runsBox?.addEventListener('click', handleRunsClick);
langZhBtn?.addEventListener('click', () => setLanguage('zh'));
langEnBtn?.addEventListener('click', () => setLanguage('en'));

tabButtons.forEach((button) => {
  button.addEventListener('click', () => {
    setActiveView(button.dataset.view);
  });
});

boot();

async function boot() {
  state.language = localStorage.getItem(STORAGE_KEYS.language) === 'en' ? 'en' : 'zh';
  applyLanguage();
  updateToolForm();
  const savedRepo = localStorage.getItem(STORAGE_KEYS.repo);
  if (savedRepo) {
    repoInput.value = savedRepo;
  }
  try {
    await refreshHealth();
    await refreshRuns({ silent: true });
  } catch (error) {
    statusText.textContent = t().statusUnavailable;
    answerBox.innerHTML = `<div class="empty-state">${escapeHtml(t().statusUnavailable)}：${escapeHtml(error.message)}</div>`;
  }
}

async function runAnalysis() {
  await runTask(t().statusAnalyzing, async () => {
    persistRepo();
    ensureRepoReady();
    const data = await postJSON('/api/ask', buildPayload());
    state.lastResult = data;
    state.selectedHitIndex = 0;
    renderResult();
    await renderMapFromRepo();
    await refreshHealth();
    setActiveView('answer');
    statusText.textContent = data.model_name ? t().statusAnalysisDoneModel(data.model_name) : t().statusAnalysisDone;
  });
}

async function generateReport() {
  await runTask(t().statusReportBuilding, async () => {
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
      reportLink.textContent = t().reportOpen;
      reportFrame.src = data.report_url;
    }

    setActiveView('report');
    statusText.textContent = t().statusReportDone;
  });
}

async function runEngineering() {
  await runTask(t().statusEngineering, async () => {
    persistRepo();
    ensureRepoReady();
    const task = questionInput.value.trim();
    if (!task) {
      throw new Error(t().needTask);
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
    statusText.textContent = t().statusEngineeringDone(data.status, data.run_id);
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

function t() {
  return I18N[state.language] || I18N.zh;
}

function setLanguage(language) {
  const next = language === 'en' ? 'en' : 'zh';
  if (state.language === next) {
    statusText.textContent = t().statusLanguage;
    return;
  }
  state.language = next;
  localStorage.setItem(STORAGE_KEYS.language, next);
  applyLanguage();
  statusText.textContent = t().statusLanguage;
}

function applyLanguage() {
  const copy = t();
  document.documentElement.lang = state.language === 'en' ? 'en' : 'zh-CN';
  document.querySelector('.brand span:last-child').textContent = 'Evidence Studio';
  tabButtons.forEach((button, index) => {
    button.textContent = copy.sidebarTabs[index] || button.textContent;
    button.setAttribute('aria-label', copy.sidebarTabs[index] || button.textContent);
  });
  langZhBtn?.classList.toggle('is-active', state.language === 'zh');
  langEnBtn?.classList.toggle('is-active', state.language === 'en');
  document.querySelector('.status-chip:nth-child(1) span').textContent = copy.cacheLabel;
  document.querySelector('.status-chip:nth-child(2) span').textContent = copy.modelLabel;
  if (modelState.textContent === I18N.zh.modelChecking || modelState.textContent === I18N.en.modelChecking) {
    modelState.textContent = copy.modelChecking;
  }
  document.querySelector('.eyebrow').textContent = copy.eyebrow;
  document.querySelector('.topbar h1').textContent = copy.title;
  document.querySelector('.repo-field span').textContent = copy.repoLabel;
  repoInput.placeholder = copy.repoPlaceholder;
  document.querySelector('.question-field span').textContent = copy.questionLabel;
  questionInput.placeholder = copy.questionPlaceholder;
  document.getElementById('askBtn').textContent = copy.ask;
  engineerBtn.textContent = copy.engineer;
  executionModeSelect.options[0].textContent = copy.workspace;
  executionModeSelect.options[1].textContent = copy.local;
  document.querySelector('.agent-toggle span').textContent = copy.aiMode;
  setPanelCopy('view-answer', copy.answerTitle, copy.answerSubtitle);
  setPanelCopy('view-evidence', copy.evidenceTitle, copy.evidenceSubtitle);
  setPanelCopy('view-map', copy.mapTitle, copy.mapSubtitle);
  setPanelCopy('view-tools', copy.toolsTitle, copy.toolsSubtitle);
  setPanelCopy('view-runs', copy.runsTitle, copy.runsSubtitle);
  setPanelCopy('view-report', copy.reportTitle, copy.reportSubtitle);
  refreshRunsBtn.textContent = copy.refresh;
  buildReportBtn.textContent = copy.buildReport;
  if (reportLink.classList.contains('disabled')) {
    reportLink.textContent = copy.reportPending;
  } else {
    reportLink.textContent = copy.reportOpen;
  }
  document.querySelectorAll('.block-head h2')[0].textContent = copy.selectedEvidence;
  document.querySelectorAll('.block-head h2')[1].textContent = copy.traceTitle;
  toolActionOptions.forEach((option, index) => {
    option.textContent = copy.toolOptions[index] || option.textContent;
  });
  toolPathInput.placeholder = copy.toolPathPlaceholder;
  startLineInput.placeholder = copy.startLinePlaceholder;
  endLineInput.placeholder = copy.endLinePlaceholder;
  searchInput.placeholder = copy.searchPlaceholder;
  commandInput.placeholder = copy.commandPlaceholder;
  updateToolForm();
  renderResult();
  renderMap();
  renderToolResult(state.lastTool);
  renderRuns();
  refreshHealth().catch(() => {});
}

function setPanelCopy(panelId, title, subtitle) {
  const panel = document.getElementById(panelId);
  panel.querySelector('.panel-head h2').textContent = title;
  panel.querySelector('.panel-head span').textContent = subtitle;
}

async function refreshRuns(options = {}) {
  try {
    const data = await getJSON('/api/runs?limit=20');
    state.runs = Array.isArray(data.runs) ? data.runs : [];
    renderRuns();
      if (!options.silent) {
      setActiveView('runs');
      statusText.textContent = t().statusRunsRefreshed;
    }
  } catch (error) {
    if (!options.silent) {
      setActiveView('runs');
      runsBox.innerHTML = `<div class="empty-state">${escapeHtml(t().failPrefix)}${escapeHtml(error.message)}</div>`;
    }
  }
}

function renderRuns() {
  if (!runsBox) {
    return;
  }
  if (!state.runs.length) {
    runsBox.innerHTML = `<div class="empty-state">${escapeHtml(t().runsEmpty)}</div>`;
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
  await runTask(t().statusOpeningRun, async () => {
    const data = await getJSON(`/api/runs/${encodeURIComponent(runId)}`);
    state.lastResult = normalizeEngineeringResult(data);
    renderResult();
    setActiveView('answer');
    statusText.textContent = t().statusOpenedRun(runId);
  }, 'runs');
}

async function resumeRun(runId) {
  await runTask(t().statusResumingRun, async () => {
    const data = await postJSON('/api/engineer/resume', { run_id: runId, max_steps: 6 });
    state.lastResult = normalizeEngineeringResult(data);
    renderResult();
    await refreshRuns({ silent: true });
    setActiveView('answer');
    statusText.textContent = t().statusResumedRun(runId, data.status);
  }, 'runs');
}

async function applyRun(runId) {
  if (!window.confirm(`Apply workspace changes from ${runId} to the source repository?`)) {
    return;
  }
  await runTask(t().statusApplying, async () => {
    const data = await postJSON('/api/runs/apply', { run_id: runId, confirm: true });
    await refreshRuns({ silent: true });
    setActiveView('runs');
    statusText.textContent = t().statusAppliedRun(data.applied_files?.length || 0, runId);
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
    await runToolAction('startup', {}, t().statusToolStartup);
    return;
  }
  if (action === 'verify') {
    await runToolAction(
      'verify',
      { query: questionInput.value.trim() || t().defaultVerifyQuery },
      t().statusToolVerify,
    );
    return;
  }
  if (action === 'list') {
    await runToolAction(
      'list',
      { path: toolPathInput.value.trim() || '.', limit: 60 },
      t().statusToolList,
    );
    return;
  }
  if (action === 'read') {
    const relpath = toolPathInput.value.trim();
    if (!relpath) {
      showToolValidation(t().needFile);
      return;
    }
    await runToolAction(
      'read',
      {
        path: relpath,
        start_line: Number(startLineInput.value || 1),
        end_line: Number(endLineInput.value || 120),
      },
      t().statusToolRead,
    );
    return;
  }
  if (action === 'search') {
    const terms = parseSearchTerms(searchInput.value);
    if (!terms.length) {
      showToolValidation(t().needSearch);
      return;
    }
    await runToolAction(
      'search',
      { terms, limit: 20 },
      t().statusToolSearch,
    );
    return;
  }
  if (action === 'run') {
    const command = commandInput.value.trim();
    if (!command) {
      showToolValidation(t().needCommand);
      return;
    }
    await runToolAction(
      'run',
      {
        command,
        timeout_seconds: 45,
      },
      t().statusToolRun,
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
    toolRunBtn.textContent = t().toolView;
  } else if (action === 'verify') {
    toolRunBtn.textContent = t().toolCheck;
  } else {
    toolRunBtn.textContent = t().toolExecute;
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
    answerBox.innerHTML = `<div class="empty-state">${escapeHtml(t().answerEmptyShort)}</div>`;
    hitList.innerHTML = `<div class="empty-state">${escapeHtml(t().evidenceEmpty)}</div>`;
    traceList.innerHTML = `<div class="empty-state">${escapeHtml(t().traceEmpty)}</div>`;
    selectionPanel.innerHTML = `<div class="empty-state">${escapeHtml(t().selectionEmpty)}</div>`;
    return;
  }

  answerBox.classList.remove('empty-state');
  answerBox.innerHTML = `${renderDiagnostics(data.diagnostics)}${renderMarkdown(data.answer || t().answerEmptyShort)}`;

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
        <span>${escapeHtml(t().diagnosticsConfidence)}</span>
        <strong>${escapeHtml(diagnostics.label)} · ${Number(diagnostics.confidence || 0).toFixed(2)}</strong>
      </article>
      <article>
        <span>${escapeHtml(t().diagnosticsCoverage)}</span>
        <strong>${escapeHtml(t().diagnosticsFiles(Number(diagnostics.evidence_count || 0), Number(diagnostics.unique_files || 0)))}</strong>
      </article>
      <article>
        <span>${escapeHtml(t().diagnosticsGraph)}</span>
        <strong>${escapeHtml(t().diagnosticsEdges(Number(diagnostics.graph_edge_count || 0)))}</strong>
      </article>
      <article>
        <span>${escapeHtml(t().diagnosticsNote)}</span>
        <strong>${escapeHtml(notes.join(state.language === 'zh' ? '；' : '; ') || t().diagnosticsNone)}</strong>
      </article>
    </section>
  `;
}

function renderEvidence(hits) {
  hitList.replaceChildren();
  if (!hits.length) {
    hitList.innerHTML = `<div class="empty-state">${escapeHtml(t().evidenceEmpty)}</div>`;
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
    traceList.innerHTML = `<div class="empty-state">${escapeHtml(t().traceEmpty)}</div>`;
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
    selectionPanel.innerHTML = `<div class="empty-state">${escapeHtml(t().selectionEmpty)}</div>`;
    return;
  }

  selectionPanel.classList.remove('empty-state');
  selectionPanel.innerHTML = `
    <div class="hit-title">${escapeHtml(hit.source_label)}</div>
    <div class="selection-meta">${escapeHtml(t().lineMeta(hit.relpath, hit.start_line, hit.end_line, hit.symbol_kind || 'file'))}</div>
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
    mapBox.innerHTML = `<div class="empty-state">${escapeHtml(t().mapEmpty)}</div>`;
    return;
  }

  const stats = data.stats || {};
  const topFiles = Array.isArray(data.top_files) ? data.top_files : [];
  const topEdges = Array.isArray(data.top_edges) ? data.top_edges : [];
  const memory = data.memory || {};

  mapBox.classList.remove('empty-state');
  mapBox.innerHTML = `
    <section class="map-section">
      <h3>${escapeHtml(t().overview)}</h3>
      <div class="map-list">
        <article class="map-item"><strong>${escapeHtml(t().fileCount)}</strong><small>${stats.file_count ?? '--'}</small></article>
        <article class="map-item"><strong>${escapeHtml(t().chunks)}</strong><small>${stats.chunk_count ?? '--'}</small></article>
        <article class="map-item"><strong>${escapeHtml(t().edgeCount)}</strong><small>${stats.graph_edge_count ?? '--'}</small></article>
      </div>
      ${memory.brief ? `<pre class="snippet">${escapeHtml(memory.brief)}</pre>` : ''}
    </section>
    <section class="map-section">
      <h3>${escapeHtml(t().topFiles)}</h3>
      <div class="map-list">
        ${topFiles.slice(0, 6).map((file) => `
          <article class="map-item">
            <strong>${escapeHtml(file.relpath)}</strong>
            <small>${escapeHtml(file.language)} · ${escapeHtml(t().lineCount)} ${file.line_count} · ${escapeHtml(t().symbols)} ${file.symbol_count}${file.roles?.length ? ` · ${escapeHtml(file.roles.join(', '))}` : ''}</small>
          </article>
        `).join('') || `<div class="empty-state">${escapeHtml(t().noTopFiles)}</div>`}
      </div>
    </section>
    <section class="map-section">
      <h3>${escapeHtml(t().keyRelations)}</h3>
      <div class="map-list">
        ${topEdges.slice(0, 6).map((edge) => `
          <article class="map-item">
            <strong>${escapeHtml(edge.label)}</strong>
            <small>${escapeHtml(edge.source)} → ${escapeHtml(edge.target)}</small>
          </article>
        `).join('') || `<div class="empty-state">${escapeHtml(t().noKeyRelations)}</div>`}
      </div>
    </section>
  `;
}

function renderToolResult(data) {
  if (!data) {
    toolOutput.innerHTML = `<div class="empty-state">${escapeHtml(t().toolEmpty)}</div>`;
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
        <strong>${escapeHtml(t().verifyCommand)}</strong>
        <small>${escapeHtml(data.verify_command)}</small>
        <div class="tool-actions">
          <button class="secondary" type="button" data-command="${escapeHtml(data.verify_command)}">${escapeHtml(t().fillCommand)}</button>
        </div>
      </article>
    `
    : '';

  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>${escapeHtml(t().startupTitle)}</strong>
      <small>${escapeHtml(data.repo_root || '')}</small>
    </div>
    ${commands.map((item) => `
      <article class="tool-card">
        <span class="tool-card-title">${escapeHtml(item.label || item.command)}</span>
        <small>${escapeHtml(item.reason || '')}</small>
        <pre class="tool-code">${escapeHtml(item.command || '')}</pre>
        <div class="tool-actions">
          <button class="secondary" type="button" data-command="${escapeHtml(item.command || '')}">${escapeHtml(t().fillCommand)}</button>
        </div>
      </article>
    `).join('') || `<div class="empty-state">${escapeHtml(t().noStartup)}</div>`}
    ${verifyBlock}
  `;
}

function renderDirectoryResult(data) {
  const entries = Array.isArray(data.entries) ? data.entries : [];
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>${escapeHtml(t().directory)}</strong>
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
          >${escapeHtml(t().open)}</button>
        </div>
      </article>
    `).join('') || `<div class="empty-state">${escapeHtml(t().emptyDirectory)}</div>`}
  `;
}

function renderReadResult(data) {
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>${escapeHtml(data.relpath || '')}</strong>
      <small>${data.start_line ?? 1}-${data.end_line ?? 1} · ${escapeHtml(t().totalLines(data.line_count))}</small>
      <pre class="tool-code">${escapeHtml(data.content || '')}</pre>
    </div>
  `;
}

function renderSearchResult(data) {
  const matches = Array.isArray(data.matches) ? data.matches : [];
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>${escapeHtml(t().textSearch)}</strong>
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
          >${escapeHtml(t().openHere)}</button>
        </div>
      </article>
    `).join('') || `<div class="empty-state">${escapeHtml(t().noSearch)}</div>`}
  `;
}

function renderCommandResult(data) {
  const supported = data.supported !== false;
  if (!supported) {
    toolOutput.innerHTML = `<div class="empty-state">${escapeHtml(data.message || t().noVerify)}</div>`;
    return;
  }
  toolOutput.innerHTML = `
    <div class="tool-card">
      <strong>${escapeHtml(data.command || '')}</strong>
      <small>${escapeHtml(t().cwdExit(data.cwd, data.exit_code))}</small>
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
    throw new Error(t().needRepo);
  }
}

function persistRepo() {
  localStorage.setItem(STORAGE_KEYS.repo, repoInput.value.trim());
}

async function refreshHealth() {
  const health = await getJSON('/api/health');
  cacheCount.textContent = health.cached_indexes ?? 0;
  modelState.textContent = health.llm_available ? t().modelReady(health.model) : t().modelNone;
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
    statusText.textContent = t().statusFailed;
    setActiveView(failureView);
    if (failureView === 'tools') {
      toolOutput.innerHTML = `<div class="empty-state">${escapeHtml(t().failPrefix)}${escapeHtml(error.message)}</div>`;
    } else {
      answerBox.innerHTML = `<div class="empty-state">${escapeHtml(t().failPrefix)}${escapeHtml(error.message)}</div>`;
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
    throw new Error(data.error || t().statusFailed);
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
    throw new Error(data.error || t().statusFailed);
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
    return data.supported === false ? t().toolDone.unsupportedVerify : t().toolDone.verify;
  }
  return t().toolDone[action] || t().toolDone.default;
}

function showToolValidation(message) {
  setActiveView('tools');
  statusText.textContent = message;
  toolOutput.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderMarkdown(source) {
  const text = String(source || '').replace(/\r\n?/g, '\n').trim();
  if (!text) {
    return `<div class="empty-state">${escapeHtml(t().answerEmptyShort)}</div>`;
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
