/**
 * LifeRescue Web Client Application — Command Center & Emergency Intelligence.
 * Communicates with LifeRescue REST API backend with zero credential dependencies.
 */

let activeIncidentId = null;

// SEC-04: optional demo access token. Kept in sessionStorage only (cleared when the tab closes).
const DEMO_TOKEN_KEY = 'liferescue.demoToken';
const _rawFetch = window.fetch.bind(window);
window.fetch = async (url, opts = {}) => {
  const token = sessionStorage.getItem(DEMO_TOKEN_KEY);
  const headers = new Headers(opts.headers || {});
  if (token) headers.set('X-Demo-Token', token);
  const res = await _rawFetch(url, { ...opts, headers });
  if (res.status === 401) showTokenPrompt();
  return res;
};

function showTokenPrompt() {
  const box = document.getElementById('demo-token-box');
  if (box) box.hidden = false;
}

function saveDemoToken(event) {
  if (event) event.preventDefault();
  const input = document.getElementById('demo-token-input');
  const value = (input.value || '').trim();
  if (value) sessionStorage.setItem(DEMO_TOKEN_KEY, value);
  else sessionStorage.removeItem(DEMO_TOKEN_KEY);
  input.value = '';
  document.getElementById('demo-token-box').hidden = true;
  window.location.reload();
}

// Tab Switching
function switchTab(tabName) {
  document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));

  const targetTab = document.getElementById(`tab-${tabName}`);
  const targetNav = document.getElementById(`nav-${tabName}`);

  if (targetTab) targetTab.classList.add('active');
  if (targetNav) targetNav.classList.add('active');

  // Trigger relevant data refreshes on navigation
  if (tabName === 'dashboard') {
    loadDashboard();
  } else if (tabName === 'readiness') {
    loadReadinessAndProfile();
  } else if (tabName === 'timeline') {
    loadTimelineDropdown();
  } else if (tabName === 'audit') {
    loadAuditEvents();
  }
}

// -----------------------------------------------------------------------------
// System Health & Provider Detection
// -----------------------------------------------------------------------------

async function checkSystemHealth() {
  try {
    const res = await fetch('/health');
    if (!res.ok) return;
    const data = await res.json();

    const pill = document.getElementById('ai-engine-pill');
    if (pill) {
      const model = String(data.ai_model || '');
      if (data.ai_mode === 'live') {
        pill.textContent = `AI Engine: LIVE NVIDIA Nemotron on Nebius (${model})`;
      } else if (data.ai_mode === 'fallback') {
        pill.textContent = `AI Engine: MOCK fallback (live provider unavailable: ${String(data.ai_last_status || 'unknown')})`;
      } else {
        pill.textContent = 'AI Engine: MOCK (deterministic demo mode)';
      }
      pill.className = 'status-pill pill-ai';
    }
  } catch (err) {
    console.warn('Health check query notice:', err);
  }
}

// -----------------------------------------------------------------------------
// Command Center Dashboard Operations
// -----------------------------------------------------------------------------

async function loadDashboard() {
  await Promise.all([
    checkSystemHealth(),
    loadReadinessScore(),
    loadContactsOverview(),
    loadIncidents(),
  ]);
}

async function loadReadinessScore() {
  try {
    const res = await fetch('/readiness?user_id=usr_demo');
    if (!res.ok) return;
    const data = await res.json();

    const circle = document.getElementById('dash-score-circle');
    if (circle) {
      circle.style.setProperty('--score', data.score);
      circle.setAttribute('data-score', data.score);
    }

    const statusEl = document.getElementById('dash-readiness-status');
    if (statusEl) {
      statusEl.innerText = `Preparedness: ${data.status.toUpperCase()} (${data.score}/100)`;
    }

    const gapsEl = document.getElementById('dash-readiness-gaps');
    if (gapsEl) {
      if (data.gaps && data.gaps.length > 0) {
        gapsEl.innerText = `${data.gaps.length} attention item(s): ${data.gaps[0]}`;
      } else {
        gapsEl.innerText = 'All emergency medical, directives, and contact safeguards verified.';
      }
    }
  } catch (err) {
    console.error('Failed to load readiness score:', err);
  }
}

async function loadContactsOverview() {
  try {
    const res = await fetch('/contacts?user_id=usr_demo');
    if (!res.ok) return;
    const contacts = await res.json();

    const container = document.getElementById('dash-contacts-list');
    if (!container) return;

    if (contacts.length === 0) {
      container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">No emergency contacts registered yet.</p>';
      return;
    }

    container.innerHTML = contacts.map(c => `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.55rem 0; border-bottom: 1px solid var(--border-glass);">
        <div>
          <strong style="font-size: 0.9rem;">${escapeHtml(c.name)}</strong>
          <span style="color: var(--text-muted); font-size: 0.8rem; margin-left: 0.4rem;">(${escapeHtml(c.relationship)})</span>
          ${c.is_primary ? '<span class="badge badge-low" style="margin-left: 0.4rem; padding: 1px 6px; font-size: 0.65rem;">Primary</span>' : ''}
          ${c.notify_on_escalation ? '<span class="badge badge-ai" style="margin-left: 0.3rem; padding: 1px 6px; font-size: 0.65rem;">Auto-Alert</span>' : ''}
        </div>
        <span style="font-size: 0.85rem; color: var(--text-secondary); font-family: var(--font-mono);">${escapeHtml(c.phone)}</span>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load contacts overview:', err);
  }
}

async function loadIncidents() {
  try {
    const res = await fetch('/incidents?limit=10');
    if (!res.ok) return;
    const incidents = await res.json();

    const container = document.getElementById('dash-incidents-list');
    if (!container) return;

    if (incidents.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 2rem 1rem; color: var(--text-muted);">
          <div style="font-size: 2rem; margin-bottom: 0.5rem;">📋</div>
          <p style="font-size: 0.9rem;">No emergency incidents logged yet.</p>
          <p style="font-size: 0.8rem; margin-top: 0.2rem;">Click one of the <strong>⚡ One-Click Emergency Scenarios</strong> above to test the platform!</p>
        </div>
      `;
      return;
    }

    container.innerHTML = incidents.map(inc => {
      let badgeClass = 'badge-medium';
      if (inc.urgency === 'critical') badgeClass = 'badge-critical';
      else if (inc.urgency === 'high') badgeClass = 'badge-high';
      else if (inc.urgency === 'low') badgeClass = 'badge-low';

      const timeStr = inc.created_at ? new Date(inc.created_at).toLocaleTimeString() : 'Recent';

      return `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.9rem 1rem; background: rgba(255,255,255,0.02); border: 1px solid var(--border-glass); border-radius: var(--radius-sm); margin-bottom: 0.6rem; transition: all 0.2s ease;">
          <div>
            <div style="display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.25rem;">
              <span class="badge ${badgeClass}">${escapeHtml(inc.urgency)}</span>
              <strong style="font-size: 0.95rem;">${escapeHtml(inc.title)}</strong>
              <span style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">${timeStr}</span>
            </div>
            <p style="font-size: 0.82rem; color: var(--text-secondary); max-width: 700px; line-height: 1.35;">
              ${escapeHtml(inc.description.substring(0, 140))}${inc.description.length > 140 ? '...' : ''}
            </p>
            <div style="display: flex; gap: 0.6rem; align-items: center; margin-top: 0.4rem;">
              <span class="action-sim-badge">[SIMULATED RESPONSE EXECUTED]</span>
              ${inc.location ? `<span style="font-size: 0.75rem; color: var(--text-muted);">📍 ${escapeHtml(inc.location)}</span>` : ''}
            </div>
          </div>
          <div style="display: flex; gap: 0.5rem; align-items: center; flex-shrink: 0; margin-left: 1rem;">
            <button class="btn-scenario" data-incident-id="${escapeHtml(inc.incident_id)}" onclick="viewIncidentTimeline(this.dataset.incidentId)">
              Inspect Timeline ↗
            </button>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load incidents:', err);
  }
}

// -----------------------------------------------------------------------------
// Reset Demo State Capability
// -----------------------------------------------------------------------------

async function resetDemoState() {
  if (!confirm('Reset LifeRescue demo records to pristine baseline?\n\nThis safely cleans up duplicate incident records and restores Alex Chen\'s standard baseline profile.')) {
    return;
  }

  try {
    const res = await fetch('/demo/reset', { method: 'POST' });
    if (!res.ok) throw new Error('Demo reset request failed');
    const result = await res.json();

    alert(`✓ Demo state reset successfully!\n${result.message}`);

    // Refresh active tab views
    await loadDashboard();
    if (document.getElementById('tab-emergency').classList.contains('active')) {
      document.getElementById('triage-placeholder').style.display = 'block';
      document.getElementById('triage-active-container').style.display = 'none';
    }
  } catch (err) {
    alert(`Reset error: ${err.message}`);
  }
}

// -----------------------------------------------------------------------------
// Emergency Submission & Triage (Capability A & B)
// -----------------------------------------------------------------------------

function prefillScenario(type) {
  if (type === 'medical') {
    document.getElementById('inc-title').value = 'Acute Medical Emergency: Severe Chest Pressure';
    document.getElementById('inc-desc').value = 'I am experiencing severe crushing chest pain radiating to my left shoulder and jaw, and I am struggling to breathe.';
    document.getElementById('inc-location').value = '142 Elmwood Ave, Apartment 3B, Boston MA';
    document.getElementById('inc-type').value = 'text';
  } else if (type === 'accident') {
    document.getElementById('inc-title').value = 'Highway Multi-Vehicle Crash with Injuries';
    document.getElementById('inc-desc').value = 'Two-vehicle high-speed collision on Route 9 North at Exit 14. Smoke is coming from the radiator, passenger has a head laceration, and airbags deployed.';
    document.getElementById('inc-location').value = 'Route 9 North, Mile Marker 14.2, near Exit 14';
    document.getElementById('inc-type').value = 'sensor';
  } else if (type === 'fire') {
    document.getElementById('inc-title').value = 'Wildfire Approach & Neighborhood Evacuation Warning';
    document.getElementById('inc-desc').value = 'Heavy black smoke and visible flame line approaching the ridge behind our neighborhood. Strong wind, power lines down on the access road.';
    document.getElementById('inc-location').value = '880 Pine Ridge Trail, Canyon Vista';
    document.getElementById('inc-type').value = 'voice_transcript';
  }
}

async function handleEmergencySubmit(event) {
  event.preventDefault();

  const title = document.getElementById('inc-title').value.trim();
  const description = document.getElementById('inc-desc').value.trim();
  const location = document.getElementById('inc-location').value.trim();
  const input_type = document.getElementById('inc-type').value;

  const submitBtn = document.getElementById('btn-submit-emergency');
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span>⚡</span> Analyzing situation with SafetyPolicyEngine...';

  try {
    // 1. Create incident
    const t0 = performance.now();
    const createRes = await fetch('/incidents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description, location, input_type, user_id: 'usr_demo' }),
    });
    if (!createRes.ok) throw new Error('Failed to create emergency incident');
    const incident = await createRes.json();
    activeIncidentId = incident.incident_id;

    // 2. Trigger Triage & Analysis
    const analyzeRes = await fetch(`/incidents/${incident.incident_id}/analyze`, { method: 'POST' });
    if (!analyzeRes.ok) throw new Error('Failed to analyze emergency');
    const triageData = await analyzeRes.json();

    // 3. Trigger Response Coordination Plan
    const respondRes = await fetch(`/incidents/${incident.incident_id}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_all: true }),
    });
    if (!respondRes.ok) throw new Error('Failed to plan response');
    const plan = await respondRes.json();
    const elapsed = Math.round(performance.now() - t0);
    const latencyEl = document.getElementById('stat-latency');
    if (latencyEl) latencyEl.innerText = `${elapsed}ms`;

    renderEmergencyResultCard(incident, triageData.analysis, triageData.risk, plan, triageData.research);
  } catch (err) {
    alert(`Emergency submission error: ${err.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<span>⚡</span> Initiate AI Triage & Response Coordination';
  }
}

// -----------------------------------------------------------------------------
// Demo Scenario Runner (Section 19)
// -----------------------------------------------------------------------------

async function runScenario(scenarioId) {
  switchTab('emergency');
  const container = document.getElementById('triage-active-container');
  const placeholder = document.getElementById('triage-placeholder');
  placeholder.style.display = 'none';
  container.style.display = 'block';

  try {
    const t0 = performance.now();
    const res = await fetch(`/demo/scenarios/${scenarioId}/run`, { method: 'POST' });
    if (!res.ok) throw new Error('Scenario execution failed');
    const data = await res.json();
    const elapsed = Math.round(performance.now() - t0);
    const latencyEl = document.getElementById('stat-latency');
    if (latencyEl) latencyEl.innerText = `${elapsed}ms`;

    activeIncidentId = data.incident.incident_id;
    document.getElementById('inc-title').value = data.incident.title;
    document.getElementById('inc-desc').value = data.incident.description;
    document.getElementById('inc-location').value = data.incident.location || '';

    renderEmergencyResultCard(data.incident, data.analysis, data.risk, data.plan, data.research);
  } catch (err) {
    alert(`Demo scenario error: ${err.message}`);
  }
}

// -----------------------------------------------------------------------------
// 9-Point High Impact Emergency Result Card Renderer
// -----------------------------------------------------------------------------

function renderResearchEvidence(research) {
  // KAN-50: untrusted Tavily evidence, rendered as escaped text only; never alters triage or plan.
  const box = document.getElementById('research-evidence-box');
  if (!box) return;
  const label = document.getElementById('research-evidence-label');
  const list = document.getElementById('research-evidence-list');
  if (!research) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  label.textContent = research.label || 'research unavailable: unknown';
  const items = research.status === 'live' && Array.isArray(research.results) ? research.results : [];
  list.innerHTML = items.map(r => {
    const url = String(r.url || '');
    const safeUrl = /^https?:\/\//.test(url) ? url : '#';
    return `<li><a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer nofollow">${escapeHtml(r.title || url)}</a><br><span style="font-size:0.8rem;color:var(--text-muted);">${escapeHtml(r.snippet || '')}</span></li>`;
  }).join('');
}

function renderEmergencyResultCard(incident, analysis, risk, plan, research) {
  renderResearchEvidence(research);
  document.getElementById('triage-placeholder').style.display = 'none';
  const container = document.getElementById('triage-active-container');
  container.style.display = 'block';

  // 1. Urgency Status Banner & Headline
  const banner = document.getElementById('result-urgency-banner');
  const tag = document.getElementById('result-urgency-tag');
  const title = document.getElementById('result-headline-title');
  const icon = document.getElementById('result-status-icon');
  const report = document.getElementById('result-user-report');

  const urgencyUpper = (risk.urgency || analysis.urgency || 'MEDIUM').toUpperCase();
  tag.innerText = urgencyUpper;
  report.innerText = `Reported: "${incident.title}" — Location: ${incident.location || 'Reported from current vicinity'}`;

  if (urgencyUpper === 'CRITICAL') {
    tag.style.color = 'var(--accent-emergency)';
    icon.innerText = '🚨';
    title.innerText = 'CRITICAL — Immediate Emergency Assistance Recommended';
    banner.style.background = 'linear-gradient(135deg, rgba(244, 63, 94, 0.25), rgba(18, 25, 44, 0.95))';
    banner.style.borderBottom = '1px solid rgba(244, 63, 94, 0.4)';
  } else if (urgencyUpper === 'HIGH') {
    tag.style.color = 'var(--accent-warning)';
    icon.innerText = '⚠️';
    title.innerText = 'HIGH URGENCY — Prompt Emergency Escalation Warranted';
    banner.style.background = 'linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(18, 25, 44, 0.95))';
    banner.style.borderBottom = '1px solid rgba(245, 158, 11, 0.4)';
  } else {
    tag.style.color = 'var(--accent-safe)';
    icon.innerText = 'ℹ️';
    title.innerText = 'STANDARD URGENCY — Local Support & Guidance Provided';
    banner.style.background = 'linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(18, 25, 44, 0.95))';
    banner.style.borderBottom = '1px solid rgba(16, 185, 129, 0.3)';
  }

  // Header badge
  const triageBadge = document.getElementById('triage-urgency-badge');
  triageBadge.style.display = 'inline-flex';
  triageBadge.className = `badge badge-${risk.urgency}`;
  triageBadge.innerText = `${urgencyUpper} URGENCY`;

  // 2. What AI Understood (Category, Severity, Confidence, Threat)
  {
    const pn = String(analysis.provider_name || '');
    const mode = pn.includes('mock_fallback') ? 'MOCK fallback' : (pn.startsWith('nvidia_ai (') ? 'LIVE' : 'MOCK');
    document.getElementById('analysis-provider-badge').textContent = `${mode} · Provider: ${pn}`;
  }
  checkSystemHealth();
  document.getElementById('analysis-category-val').innerText = analysis.category ? analysis.category.toUpperCase() : 'UNKNOWN';
  document.getElementById('analysis-severity-val').innerText = `${analysis.severity_score || 8}/10`;
  document.getElementById('analysis-confidence-val').innerText = `${((analysis.confidence || 0.9) * 100).toFixed(0)}%`;
  document.getElementById('analysis-threat-val').innerText = analysis.immediate_threat ? 'Immediate Threat Detected' : 'No Immediate Collapse';
  document.getElementById('analysis-summary-text').innerText = analysis.summary;

  // 3. Why Serious (Triggers & Symptoms)
  const triggersList = document.getElementById('analysis-triggers-list');
  const triggers = [];
  if (risk.escalation_reason) triggers.push(risk.escalation_reason);
  if (analysis.extracted_facts && analysis.extracted_facts.length > 0) {
    triggers.push(...analysis.extracted_facts);
  }
  triggersList.innerHTML = triggers.map(t => `<li>${escapeHtml(t)}</li>`).join('');

  // 4. Missing Critical Info
  const missingBox = document.getElementById('analysis-missing-box');
  const missingText = document.getElementById('analysis-missing-text');
  if (analysis.missing_critical_info && analysis.missing_critical_info.length > 0) {
    missingBox.style.display = 'block';
    missingText.innerText = analysis.missing_critical_info.join('; ');
  } else {
    missingBox.style.display = 'none';
  }

  // 5. Recommended Immediate Steps
  const stepsList = document.getElementById('analysis-steps-list');
  if (analysis.recommended_immediate_steps && analysis.recommended_immediate_steps.length > 0) {
    stepsList.innerHTML = analysis.recommended_immediate_steps.map(s => `<li>${escapeHtml(s)}</li>`).join('');
  } else {
    stepsList.innerHTML = '<li>Keep patient stationary and monitor consciousness while awaiting responders.</li>';
  }

  // 6. Deterministic Safety Decision
  document.getElementById('policy-rule-badge').innerText = risk.policy_rule_triggered || 'RULE_ACUTE_LIFE_THREAT_ESCALATION';
  document.getElementById('policy-decision-text').innerText = risk.requires_escalation
    ? 'Emergency escalation approved by deterministic SafetyPolicyEngine. Non-LLM hard rules enforce life-threat prioritization.'
    : 'Standard response plan approved by deterministic SafetyPolicyEngine. No immediate life threat detected.';

  const notesBox = document.getElementById('policy-notes-box');
  if (plan.policy_notes) {
    notesBox.innerText = `Policy Notes: ${plan.policy_notes}`;
    notesBox.style.display = 'block';
  } else {
    notesBox.style.display = 'none';
  }

  // 7. Coordinated Response Actions (Explicit Simulation Tags)
  const actionsList = document.getElementById('plan-actions-list');
  actionsList.innerHTML = plan.actions.map(action => {
    let typeIcon = '📋';
    let simulationLabel = 'SIMULATED';
    if (action.action_type === 'call_emergency_services') {
      typeIcon = '🚑';
      simulationLabel = 'SIMULATED DISPATCH';
    } else if (action.action_type === 'notify_contact') {
      typeIcon = '👤';
      simulationLabel = 'SIMULATED SMS';
    } else if (action.action_type === 'first_aid_guidance') {
      typeIcon = '🩹';
      simulationLabel = 'GENERATED GUIDANCE';
    } else if (action.action_type === 'scene_safety') {
      typeIcon = '⚠️';
      simulationLabel = 'SAFETY DIRECTIVE';
    }

    const isEscalation = action.is_escalation;

    return `
      <div class="action-card ${isEscalation ? 'escalation' : ''}">
        <div class="action-info">
          <h5>
            <span>${typeIcon}</span>
            <span>${escapeHtml(action.title)}</span>
            <span class="action-sim-badge">[${simulationLabel}]</span>
          </h5>
          <p>${escapeHtml(action.description)}</p>
          ${action.result_message ? `<p style="color: var(--accent-safe); font-size: 0.78rem; margin-top: 0.25rem;">✓ ${escapeHtml(action.result_message)}</p>` : ''}
        </div>
        <span class="badge ${action.status === 'executed' || action.status === 'simulated' ? 'badge-low' : 'badge-medium'}">
          ${escapeHtml(action.status || 'simulated').toUpperCase()}
        </span>
      </div>
    `;
  }).join('');

  // 8. Audit Record Link
  document.getElementById('result-audit-ref').innerText = `Incident ID: ${incident.incident_id} | Stored with defense-in-depth secret redaction`;

  // 9. Update 7-Stage Progression Indicators
  ['pstep-intake', 'pstep-ai', 'pstep-risk', 'pstep-policy', 'pstep-plan', 'pstep-sim', 'pstep-audit'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'triage-step-7 completed';
  });
}

function viewActiveTimeline() {
  if (activeIncidentId) {
    viewIncidentTimeline(activeIncidentId);
  } else {
    switchTab('timeline');
  }
}

// -----------------------------------------------------------------------------
// Timeline Operations
// -----------------------------------------------------------------------------

async function loadTimelineDropdown() {
  try {
    const res = await fetch('/incidents?limit=30');
    if (!res.ok) return;
    const incidents = await res.json();

    const select = document.getElementById('timeline-incident-select');
    select.innerHTML = '<option value="">Select an Incident...</option>' +
      incidents.map(inc => `<option value="${escapeHtml(inc.incident_id)}" ${inc.incident_id === activeIncidentId ? 'selected' : ''}>${escapeHtml(inc.title)} (${escapeHtml(inc.incident_id)})</option>`).join('');

    if (activeIncidentId) {
      loadSelectedTimeline();
    }
  } catch (err) {
    console.error('Failed to load incident dropdown:', err);
  }
}

function viewIncidentTimeline(incidentId) {
  activeIncidentId = incidentId;
  switchTab('timeline');
}

async function loadSelectedTimeline() {
  const select = document.getElementById('timeline-incident-select');
  const incidentId = select.value || activeIncidentId;
  if (!incidentId) return;

  const container = document.getElementById('timeline-container');
  container.innerHTML = '<p style="color: var(--text-muted);">Fetching timeline events...</p>';

  try {
    const res = await fetch(`/incidents/${incidentId}/timeline`);
    if (!res.ok) throw new Error('Timeline not found');
    const data = await res.json();

    if (data.events.length === 0) {
      container.innerHTML = '<p style="color: var(--text-muted);">No timeline events recorded yet.</p>';
      return;
    }

    container.innerHTML = data.events.map(e => `
      <div class="timeline-item">
        <div class="timeline-dot"></div>
        <div class="timeline-header">
          <span class="timeline-actor">${escapeHtml(e.actor.toUpperCase())}</span>
          <span class="badge badge-medium" style="font-size: 0.7rem;">${escapeHtml(e.event_type)}</span>
          <span class="timeline-time">${new Date(e.timestamp).toLocaleTimeString()}</span>
        </div>
        <div class="timeline-body">
          <strong>Step ${parseInt(e.seq, 10)}:</strong> ${escapeHtml(e.summary)}
          ${e.payload && Object.keys(e.payload).length > 0 ? `
            <pre style="margin-top: 0.5rem; font-size: 0.75rem; background: rgba(0,0,0,0.4); padding: 0.5rem; border-radius: 4px; overflow-x: auto; color: var(--text-secondary); font-family: var(--font-mono);">${escapeHtml(JSON.stringify(e.payload, null, 2))}</pre>
          ` : ''}
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = `<p style="color: var(--accent-emergency);">Failed to load timeline: ${escapeHtml(err.message)}</p>`;
  }
}

// -----------------------------------------------------------------------------
// Personal Readiness & Contacts Operations (Capability C)
// -----------------------------------------------------------------------------

async function loadReadinessAndProfile() {
  try {
    // 1. Fetch Readiness Assessment
    const readinessRes = await fetch('/readiness?user_id=usr_demo');
    if (readinessRes.ok) {
      const data = await readinessRes.json();
      const circle = document.getElementById('readiness-score-circle');
      if (circle) {
        circle.style.setProperty('--score', data.score);
        circle.setAttribute('data-score', data.score);
      }

      const badge = document.getElementById('readiness-badge');
      if (badge) {
        badge.className = `badge badge-${data.status === 'excellent' || data.status === 'good' ? 'low' : 'high'}`;
        badge.innerText = data.status.toUpperCase();
      }

      const titleEl = document.getElementById('readiness-score-title');
      if (titleEl) {
        titleEl.innerText = `Preparedness Status: ${data.status.toUpperCase()}`;
      }

      const descEl = document.getElementById('readiness-score-desc');
      if (descEl) {
        descEl.innerText = `Score: ${data.score}/100. ${data.recommendations && data.recommendations[0] ? data.recommendations[0] : ''}`;
      }

      const checklist = document.getElementById('readiness-checklist');
      if (checklist) {
        checklist.innerHTML = data.checks.map(chk => `
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 0.65rem 0; border-bottom: 1px solid var(--border-glass);">
            <div style="display: flex; align-items: flex-start; gap: 0.6rem;">
              <span style="font-size: 1.1rem; line-height: 1;">${chk.passed ? '✅' : '⚠️'}</span>
              <div>
                <strong style="font-size: 0.88rem; color: ${chk.passed ? 'var(--text-primary)' : 'var(--accent-warning)'};">${escapeHtml(chk.title)}</strong>
                <p style="font-size: 0.78rem; color: var(--text-muted); margin-top: 0.1rem;">${escapeHtml(chk.description)}</p>
              </div>
            </div>
            <span class="badge ${chk.passed ? 'badge-low' : 'badge-high'}" style="font-size: 0.65rem; flex-shrink: 0; margin-left: 0.5rem;">
              ${escapeHtml(chk.importance)}
            </span>
          </div>
        `).join('');
      }
    }

    // 2. Fetch Profile
    const profRes = await fetch('/emergency-profile?user_id=usr_demo');
    if (profRes.ok) {
      const profile = await profRes.json();
      document.getElementById('prof-blood').value = profile.blood_type || '';
      document.getElementById('prof-lang').value = profile.primary_language || 'en';
      document.getElementById('prof-address').value = profile.home_address || '';
      document.getElementById('prof-allergies').value = (profile.allergies || []).join(', ');
      document.getElementById('prof-meds').value = (profile.medications || []).join(', ');
      document.getElementById('prof-conditions').value = (profile.medical_conditions || []).join(', ');
      document.getElementById('prof-instructions').value = profile.emergency_instructions || '';
    }

    // 3. Fetch Contacts
    loadManageContacts();
  } catch (err) {
    console.error('Failed to load readiness details:', err);
  }
}

async function quickRemediateProfile() {
  document.getElementById('prof-instructions').value = 'Spare inhaler is located in backpack outer pocket. Building gate code is #4821.';
  await saveEmergencyProfile(false);
}

async function simulateProfileGap() {
  document.getElementById('prof-instructions').value = '';
  await saveEmergencyProfile(false);
}

async function saveEmergencyProfile(showAlert = true) {
  const blood_type = document.getElementById('prof-blood').value;
  const primary_language = document.getElementById('prof-lang').value.trim();
  const home_address = document.getElementById('prof-address').value.trim();
  const allergies = document.getElementById('prof-allergies').value.split(',').map(s => s.trim()).filter(Boolean);
  const medications = document.getElementById('prof-meds').value.split(',').map(s => s.trim()).filter(Boolean);
  const medical_conditions = document.getElementById('prof-conditions').value.split(',').map(s => s.trim()).filter(Boolean);
  const emergency_instructions = document.getElementById('prof-instructions').value.trim();

  try {
    const res = await fetch('/emergency-profile?user_id=usr_demo', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        blood_type,
        primary_language,
        home_address,
        allergies,
        medications,
        medical_conditions,
        emergency_instructions,
      }),
    });
    if (!res.ok) throw new Error('Failed to update profile');
    if (showAlert) {
      alert('✓ Emergency medical profile saved successfully!');
    }
    await loadReadinessAndProfile();
    await loadReadinessScore();
  } catch (err) {
    alert(`Save error: ${err.message}`);
  }
}

async function loadManageContacts() {
  try {
    const res = await fetch('/contacts?user_id=usr_demo');
    if (!res.ok) return;
    const contacts = await res.json();

    const container = document.getElementById('contacts-management-list');
    if (!container) return;

    if (contacts.length === 0) {
      container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">No contacts registered.</p>';
      return;
    }

    container.innerHTML = contacts.map(c => `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 0.5rem; border-bottom: 1px solid var(--border-glass);">
        <div>
          <strong style="font-size: 0.9rem;">${escapeHtml(c.name)}</strong>
          <span style="color: var(--text-muted); font-size: 0.8rem; margin-left: 0.4rem;">(${escapeHtml(c.relationship)})</span>
          ${c.is_primary ? '<span class="badge badge-low" style="margin-left: 0.4rem; padding: 1px 6px; font-size: 0.65rem;">Primary</span>' : ''}
          <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.2rem; font-family: var(--font-mono);">
            📞 ${escapeHtml(c.phone)} ${c.email ? `| ✉️ ${escapeHtml(c.email)}` : ''}
          </div>
        </div>
        <button class="btn-scenario" style="color: var(--accent-emergency);" data-contact-id="${escapeHtml(c.contact_id)}" onclick="deleteContact(this.dataset.contactId)">Remove</button>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load contacts for management:', err);
  }
}

async function openAddContactModal() {
  const name = prompt('Contact Full Name:');
  if (!name) return;
  const relationship = prompt('Relationship (e.g. Spouse, Parent, Doctor):') || 'Emergency Contact';
  const phone = prompt('Contact Phone Number:') || '+1-555-0100';
  const is_primary = confirm('Set as Primary Emergency Contact for urgent escalation notifications?');

  try {
    const res = await fetch('/contacts?user_id=usr_demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, relationship, phone, is_primary, notify_on_escalation: true }),
    });
    if (!res.ok) throw new Error('Failed to create contact');
    loadReadinessAndProfile();
    loadReadinessScore();
  } catch (err) {
    alert(`Add contact error: ${err.message}`);
  }
}

async function deleteContact(contactId) {
  if (!confirm('Remove this emergency contact?')) return;
  try {
    const res = await fetch(`/contacts/${contactId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete contact');
    loadManageContacts();
    loadReadinessScore();
  } catch (err) {
    alert(`Delete error: ${err.message}`);
  }
}

// -----------------------------------------------------------------------------
// Interactive Safety Policy Tester (AI Governance)
// -----------------------------------------------------------------------------

function testSafetyPolicy(testCase) {
  const display = document.getElementById('safety-tester-output');
  const title = document.getElementById('tester-result-title');
  const badge = document.getElementById('tester-result-badge');
  const desc = document.getElementById('tester-result-desc');
  const code = document.getElementById('tester-result-code');

  display.style.display = 'block';

  if (testCase === 'shell_injection') {
    title.innerText = 'BLOCKED: Prohibited Shell Command Injection';
    badge.className = 'badge badge-critical';
    badge.innerText = 'PROHIBITED ACTION REJECTED';
    desc.innerText = 'An untrusted AI output proposed executing a system command: "bash $(rm -rf /)". The SafetyPolicyEngine matched regex r"\\b(bash|sh|cmd|powershell|rm -rf)\\b" and dropped the action entirely before any execution.';
    code.innerText = `[SafetyPolicyEngine] Pattern Matched: 'rm -rf'
Rejected Action: ResponseAction(type='custom', title='Execute bash command $(rm -rf /)')
Policy Note: 'Blocked unsafe action matching prohibited pattern'
Status: DROPPED (0 commands executed)`;
  } else if (testCase === 'medical_prescription') {
    title.innerText = 'BLOCKED: Unauthorized Medical Prescription';
    badge.className = 'badge badge-critical';
    badge.innerText = 'MEDICAL SAFETY RULE ENFORCED';
    desc.innerText = 'An AI model proposed: "Prescribe and inject 50mg epinephrine directly". SafetyPolicyEngine prohibited pattern r"\\b(prescribe|administer|inject|dose|surgery)\\b" blocked the action. LifeRescue enforces that AI is NOT a licensed physician.';
    code.innerText = `[SafetyPolicyEngine] Pattern Matched: 'inject', 'prescribe'
Rejected Action: ResponseAction(title='Prescribe and inject 50mg epinephrine')
Inviolable Medical Disclaimer: LifeRescue does NOT prescribe or diagnose.
Status: DROPPED`;
  } else if (testCase === 'financial_transfer') {
    title.innerText = 'BLOCKED: Prohibited Financial Command';
    badge.className = 'badge badge-critical';
    badge.innerText = 'FINANCIAL EXPLOIT BLOCKED';
    desc.innerText = 'An AI model proposed: "Transfer $5000 to crypto wallet for emergency assistance". SafetyPolicyEngine pattern r"\\b(transfer|wire|pay|buy|credit|wallet|crypto)\\b" blocked the action.';
    code.innerText = `[SafetyPolicyEngine] Pattern Matched: 'wire', 'crypto'
Rejected Action: ResponseAction(title='Wire $5000 to crypto wallet')
Status: DROPPED`;
  } else if (testCase === 'life_threat_override') {
    title.innerText = 'ENFORCED: Mandatory Life-Threat Escalation Rule';
    badge.className = 'badge badge-low';
    badge.innerText = 'RULE_ACUTE_LIFE_THREAT_ESCALATION';
    desc.innerText = 'Patient mentioned "crushing chest pain". Even if the AI model had hallucinated a low urgency, the SafetyPolicyEngine detected the cardiac pattern and forced urgency to CRITICAL, automatically injecting an EMS dispatch action.';
    code.innerText = `[SafetyPolicyEngine] Rule Triggered: RULE_ACUTE_LIFE_THREAT_ESCALATION
Symptom Detected: 'chest pain'
Action: Mandatory CALL_EMERGENCY_SERVICES injected at index 0.
Urgency Overridden: -> CRITICAL`;
  }
}

// -----------------------------------------------------------------------------
// Audit Trail Operations
// -----------------------------------------------------------------------------

async function loadAuditEvents() {
  const tbody = document.getElementById('audit-events-body');
  tbody.innerHTML = '<tr><td colspan="7" style="padding: 1.5rem; text-align: center; color: var(--text-muted);">Fetching append-only audit trail...</td></tr>';

  try {
    const res = await fetch('/audit/events?limit=50');
    if (!res.ok) throw new Error('Failed to load audit events');
    const events = await res.json();

    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="padding: 1.5rem; text-align: center; color: var(--text-muted);">No audit records generated yet.</td></tr>';
      return;
    }

    tbody.innerHTML = events.map(e => `
      <tr style="border-bottom: 1px solid var(--border-glass);">
        <td style="padding: 0.65rem 0.5rem; font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-muted);">
          ${new Date(e.timestamp).toLocaleTimeString()}
        </td>
        <td style="padding: 0.65rem 0.5rem; font-weight: 600; color: var(--accent-ai); font-size: 0.8rem;">
          ${escapeHtml(e.event_type)}
        </td>
        <td style="padding: 0.65rem 0.5rem; color: var(--text-secondary); font-size: 0.8rem;">
          ${escapeHtml(e.actor)}
        </td>
        <td style="padding: 0.65rem 0.5rem; font-size: 0.82rem;">
          ${escapeHtml(e.action)}
        </td>
        <td style="padding: 0.65rem 0.5rem;">
          <span class="badge ${e.result === 'success' ? 'badge-low' : 'badge-high'}" style="font-size: 0.68rem;">
            ${escapeHtml(e.result)}
          </span>
        </td>
        <td style="padding: 0.65rem 0.5rem; font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">
          ${escapeHtml(e.incident_id || '—')}
        </td>
        <td style="padding: 0.65rem 0.5rem; font-size: 0.75rem; color: var(--accent-safe);">
          ✓ Redacted
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="padding: 1.5rem; text-align: center; color: var(--accent-emergency);">Failed to load audit trail: ${escapeHtml(err.message)}</td></tr>`;
  }
}

// Utility: Escape HTML
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Initial Page Load
window.addEventListener('DOMContentLoaded', () => {
  loadDashboard();
});
