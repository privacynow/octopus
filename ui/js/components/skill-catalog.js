/**
 * Skill catalog — runtime skills list (placeholder, expanded in Phase 5).
 */
function renderSkillCatalog(container) {
    container.innerHTML = `
        <div class="page-header">
            <h2>Skills</h2>
            <p>Runtime skill catalog</p>
        </div>
        <div id="skill-list" class="loading">Loading skills...</div>
    `;

    // Skills are served via /v1/catalog/skills (existing route, unchanged)
    fetch('/v1/catalog/skills', { credentials: 'same-origin' })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`${r.status}`)))
        .then(data => {
            const skills = Array.isArray(data) ? data : (data.skills || []);
            const el = document.getElementById('skill-list');
            if (!skills || skills.length === 0) {
                el.innerHTML = '<div class="empty-state">No skills installed</div>';
                return;
            }
            el.innerHTML = skills.map(s => `
                <div class="card" style="cursor:default">
                    <div class="card-title">${esc(s.slug || s.name || '')}</div>
                    <div class="card-subtitle">
                        ${esc(s.display_name || '')}
                        ${s.status ? ` &middot; <span class="badge badge-${s.status}">${esc(s.status)}</span>` : ''}
                    </div>
                </div>
            `).join('');
        })
        .catch(err => {
            document.getElementById('skill-list').innerHTML =
                `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
        });
}
