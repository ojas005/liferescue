/**
 * LifeRescue Web Client Application.
 * Communicates with LifeRescue REST API backend.
 */

let activeIncidentId = null;

// Tab Switching
function switchTab(tabName) {
  document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));

  const targetTab = document.getElementById(`tab-${tabName}`);
  const targetNav = document.getElementById(`nav-${tabName}`);

  if (targetTab) targetTab.classList.add('active');
  if (targetNav) targetNav.classList.add('active');

  // Trigger data refreshes on navigation
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
// Dashboard Operations
// -----------------------------------------------------------------------------

async function loadDashboard() {
  loadReadinessScore();
  loadContactsOverview();
  loadIncidents();
}

async function loadReadinessScore() {
  try {
    const res = await fetch('/readiness?user_id=usr_demo');
    if (!res.ok) return;
    const data = await res.json();

    const circle = document.getElementById('dash-score-circle');
    circle.style.setProperty('--score', data.score);
    circle.setAttribute('data-score', data.score);

    document.getElementById('dash-readiness-status').innerText = `Preparedness: ${data.status.toUpperCase()} (${data.score}/100)`;
    
    if (data.gaps && data.gaps.length > 0) {
      document.getElementById('dash-readiness-gaps').innerText = `${data.gaps.length} attention item(s): ${data.gaps[0]}`;
    } else {
      document.getElementById('dash-readiness-gaps').innerText = 'All emergency medical and contact safeguards verified.';
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
    if (contacts.length === 0) {
      container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">No contacts registered yet.</p>';
      return;
    }

    container.innerHTML = contacts.map(c => `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid var(--border-glass);">
        <div>
          <strong style="font-size: 0.9rem;">${escapeHtml(c.name)}</strong>
          <span style="color: var(--text-muted); font-size: 0.8rem; margin-left: 0.4rem;">(${escapeHtml(c.relationship)})</span>
          ${c.is_primary ? '<span class="badge badge-low" style="margin-left: 0.4rem; padding: 1px 6px;">Primary</span>' : ''}
        </div>
        <span style="font-size: 0.85rem; color: var(--text-secondary);">${escapeHtml(c.phone)}</span>
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
    if (incidents.length === 0) {
      container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">No emergency incidents logged yet. Try running a Demo Scenario above!</p>';
      return;
    }

    container.innerHTML = incidents.map(inc => {
      const urgencyClass = `badge-${inc.urgency}`;
      return `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.8rem; background: rgba(255,255,255,0.02); border: 1px solid var(--border-glass); border-radius: var(--radius-sm); margin-bottom: 0.6rem;">
          <div>
            <div style="display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.2rem;">
              <span class="badge ${urgencyClass}">${inc.urgency}</span>
              <strong style="font-size: 0.95rem;">${escapeHtml(inc.title)}</strong>
            </div>
            <p style="font-size: 0.8rem; color: var(--text-secondary); max-width: 650px;">
              ${escapeHtml(inc.description.substring(0, 110))}...
            </p>
          </div>
          <div style="display: flex; gap: 0.5rem; align-items: center;">
            <button class="btn-scenario" data-incident-id="${escapeHtml(inc.incident_id)}" onclick="viewIncidentTimeline(this.dataset.incidentId)">Timeline ↗</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load incidents:', err);
  }
}

// -----------------------------------------------------------------------------
// Emergency Submission & Triage
// -----------------------------------------------------------------------------

async function handleEmergencySubmit(event) {
  event.preventDefault();

  const title = document.getElementById('inc-title').value.trim();
  const description = document.getElementById('inc-desc').value.trim();
  const location = document.getElementById('inc-location').value.trim();
  const input_type = document.getElementById('inc-type').value;

  const submitBtn = document.getElementById('btn-submit-emergency');
  submitBtn.disabled = true;
  submitBtn.innerText = 'Analyzing situation with Safety Policy...';

  try {
    // 1. Create incident
    const createRes = await fetch('/incidents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description, location, input_type, user_id: 'usr_demo' }),
    });
    if (!createRes.ok) throw new Error('Failed to create incident');
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

    renderTriageResult(incident, triageData.analysis, triageData.risk, plan);
  } catch (err) {
    alert(`Emergency submission error: ${err.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<span>⚡</span> Initiate AI Triage & Response';
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

  document.getElementById('analysis-summary').innerText = 'Initializing deterministic AI triage analysis...';

  try {
    const res = await fetch(`/demo/scenarios/${scenarioId}/run`, { method: 'POST' });
    if (!res.ok) throw new Error('Scenario execution failed');
    const data = await res.json();

    activeIncidentId = data.incident.incident_id;
    document.getElementById('inc-title').value = data.incident.title;
    document.getElementById('inc-desc').value = data.incident.description;
    document.getElementById('inc-location').value = data.incident.location || '';

    renderTriageResult(data.incident, data.analysis, data.risk, data.plan);
  } catch (err) {
    alert(`Demo scenario error: ${err.message}`);
  }
}

function renderTriageResult(incident, analysis, risk, plan) {
  document.getElementById('triage-placeholder').style.display = 'none';
  const container = document.getElementById('triage-active-container');
  container.style.display = 'block';

  // Badge
  const badge = document.getElementById('triage-urgency-badge');
  badge.style.display = 'inline-flex';
  badge.className = `badge badge-${risk.urgency}`;
  badge.innerText = `${risk.urgency} Urgency`;

  // Analysis card
  document.getElementById('analysis-category').innerText = `${analysis.category} Incident (Provider: ${analysis.provider_name})`;
  document.getElementById('analysis-severity').innerText = `Severity: ${analysis.severity_score}/10 | Confidence: ${(analysis.confidence * 100).toFixed(0)}%`;
  document.getElementById('analysis-summary').innerText = analysis.summary;

  const missingBox = document.getElementById('analysis-missing-box');
  if (analysis.missing_critical_info && analysis.missing_critical_info.length > 0) {
    missingBox.style.display = 'block';
    document.getElementById('analysis-missing-text').innerText = analysis.missing_critical_info.join('; ');
  } else {
    missingBox.style.display = 'none';
  }

  // Action cards
  const actionsList = document.getElementById('plan-actions-list');
  actionsList.innerHTML = plan.actions.map(action => {
    const isEscalation = action.is_escalation;
    return `
      <div class="action-card ${isEscalation ? 'escalation' : ''}">
        <div class="action-info">
          <h5>${escapeHtml(action.title)} ${action.mocked ? '<span class="badge badge-medium" style="font-size: 0.65rem;">SIMULATED</span>' : ''}</h5>
          <p>${escapeHtml(action.description)}</p>
          ${action.result_message ? `<p style="color: var(--accent-safe); font-size: 0.78rem; margin-top: 0.2rem;">✓ ${escapeHtml(action.result_message)}</p>` : ''}
        </div>
        <span class="badge ${action.status === 'executed' || action.status === 'simulated' ? 'badge-low' : 'badge-medium'}">
          ${escapeHtml(action.status)}
        </span>
      </div>
    `;
  }).join('');

  // Update step indicators
  document.getElementById('step-intake').className = 'triage-step completed';
  document.getElementById('step-ai').className = 'triage-step completed';
  document.getElementById('step-policy').className = 'triage-step completed';
  document.getElementById('step-actions').className = 'triage-step completed';
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
          <span class="timeline-actor">${escapeHtml(e.actor)}</span>
          <span class="badge badge-medium" style="font-size: 0.7rem;">${escapeHtml(e.event_type)}</span>
          <span class="timeline-time">${new Date(e.timestamp).toLocaleTimeString()}</span>
        </div>
        <div class="timeline-body">
          <strong>Step ${parseInt(e.seq, 10)}:</strong> ${escapeHtml(e.summary)}
          ${e.payload && Object.keys(e.payload).length > 0 ? `
            <pre style="margin-top: 0.4rem; font-size: 0.75rem; background: rgba(0,0,0,0.3); padding: 0.4rem; border-radius: 4px; overflow-x: auto;">${escapeHtml(JSON.stringify(e.payload, null, 2))}</pre>
          ` : ''}
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = `<p style="color: var(--accent-emergency);">Failed to load timeline: ${escapeHtml(err.message)}</p>`;
  }
}

// -----------------------------------------------------------------------------
// Readiness & Profile Operations
// -----------------------------------------------------------------------------

async function loadReadinessAndProfile() {
  try {
    // 1. Fetch Readiness Assessment
    const readinessRes = await fetch('/readiness?user_id=usr_demo');
    if (readinessRes.ok) {
      const data = await readinessRes.json();
      const circle = document.getElementById('readiness-score-circle');
      circle.style.setProperty('--score', data.score);
      circle.setAttribute('data-score', data.score);

      const badge = document.getElementById('readiness-badge');
      badge.className = `badge badge-${data.status === 'excellent' || data.status === 'good' ? 'low' : 'high'}`;
      badge.innerText = data.status.toUpperCase();

      document.getElementById('readiness-score-title').innerText = `Preparedness Status: ${data.status.toUpperCase()}`;
      document.getElementById('readiness-score-desc').innerText = `Score: ${data.score}/100. ${data.recommendations[0] || ''}`;

      const checklist = document.getElementById('readiness-checklist');
      checklist.innerHTML = data.checks.map(chk => `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid var(--border-glass);">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span>${chk.passed ? '✅' : '⚠️'}</span>
            <div>
              <strong style="font-size: 0.85rem; color: ${chk.passed ? 'var(--text-primary)' : 'var(--accent-warning)'};">${escapeHtml(chk.title)}</strong>
              <p style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(chk.description)}</p>
            </div>
          </div>
          <span class="badge ${chk.passed ? 'badge-low' : 'badge-high'}" style="font-size: 0.65rem;">
            ${escapeHtml(chk.importance)}
          </span>
        </div>
      `).join('');
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

async function loadManageContacts() {
  try {
    const res = await fetch('/contacts?user_id=usr_demo');
    if (!res.ok) return;
    const contacts = await res.json();

    const container = document.getElementById('contacts-management-list');
    if (contacts.length === 0) {
      container.innerHTML = '<p style="color: var(--text-muted);">No contacts registered.</p>';
      return;
    }

    container.innerHTML = contacts.map(c => `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 0.5rem; border-bottom: 1px solid var(--border-glass);">
        <div>
          <strong>${escapeHtml(c.name)}</strong>
          <span style="color: var(--text-muted); font-size: 0.8rem; margin-left: 0.4rem;">(${escapeHtml(c.relationship)})</span>
          ${c.is_primary ? '<span class="badge badge-low" style="margin-left: 0.4rem; padding: 1px 6px;">Primary</span>' : ''}
          <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.2rem;">
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

async function saveEmergencyProfile() {
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
    alert('Emergency medical profile saved successfully!');
    loadReadinessAndProfile();
  } catch (err) {
    alert(`Save error: ${err.message}`);
  }
}

async function openAddContactModal() {
  const name = prompt('Contact Full Name:');
  if (!name) return;
  const relationship = prompt('Relationship (e.g. Spouse, Parent, Doctor):') || 'Contact';
  const phone = prompt('Contact Phone Number:') || '+1-555-0100';
  const is_primary = confirm('Set as Primary Contact for urgent notifications?');

  try {
    const res = await fetch('/contacts?user_id=usr_demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, relationship, phone, is_primary, notify_on_escalation: true }),
    });
    if (!res.ok) throw new Error('Failed to create contact');
    loadReadinessAndProfile();
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
// Audit Trail Operations
// -----------------------------------------------------------------------------

async function loadAuditEvents() {
  const tbody = document.getElementById('audit-events-body');
  tbody.innerHTML = '<tr><td colspan="6" style="padding: 1.5rem; text-align: center; color: var(--text-muted);">Fetching immutable audit trail...</td></tr>';

  try {
    const res = await fetch('/audit/events?limit=50');
    if (!res.ok) throw new Error('Failed to load audit events');
    const events = await res.json();

    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding: 1.5rem; text-align: center; color: var(--text-muted);">No audit records generated yet.</td></tr>';
      return;
    }

    tbody.innerHTML = events.map(e => `
      <tr style="border-bottom: 1px solid var(--border-glass);">
        <td style="padding: 0.6rem 0.5rem; font-family: monospace; font-size: 0.8rem; color: var(--text-muted);">
          ${new Date(e.timestamp).toLocaleTimeString()}
        </td>
        <td style="padding: 0.6rem 0.5rem; font-weight: 600; color: var(--accent-ai);">
          ${escapeHtml(e.event_type)}
        </td>
        <td style="padding: 0.6rem 0.5rem; color: var(--text-secondary);">
          ${escapeHtml(e.actor)}
        </td>
        <td style="padding: 0.6rem 0.5rem;">
          ${escapeHtml(e.action)}
        </td>
        <td style="padding: 0.6rem 0.5rem;">
          <span class="badge ${e.result === 'success' ? 'badge-low' : 'badge-high'}" style="font-size: 0.7rem;">
            ${escapeHtml(e.result)}
          </span>
        </td>
        <td style="padding: 0.6rem 0.5rem; font-family: monospace; font-size: 0.75rem; color: var(--text-muted);">
          ${escapeHtml(e.incident_id || '—')}
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="padding: 1.5rem; text-align: center; color: var(--accent-emergency);">Failed to load audit trail: ${escapeHtml(err.message)}</td></tr>`;
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
