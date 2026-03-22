/**
 * Capability list — global capability overrides (operator only).
 */
function renderCapabilityList(container) {
    container.innerHTML = `
        <div class="page-header">
            <h2>Capabilities</h2>
            <p>Global capability overrides</p>
        </div>
        <div id="cap-list" class="loading">Loading...</div>
    `;

    API.listCapabilities().then(caps => {
        const el = document.getElementById('cap-list');
        if (!caps || caps.length === 0) {
            el.innerHTML = '<div class="empty-state">No capabilities declared</div>';
            return;
        }
        el.innerHTML = caps.map(c => {
            const enabled = c.enabled !== false;
            return `
                <div class="card" style="cursor:default;display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <div class="card-title">${esc(c.name || c.capability_name || '')}</div>
                    </div>
                    <button class="btn ${enabled ? 'btn-danger' : 'btn-primary'}"
                        onclick="_toggleCapability('${esc(c.name || c.capability_name)}', ${!enabled})">
                        ${enabled ? 'Disable' : 'Enable'}
                    </button>
                </div>
            `;
        }).join('');
    }).catch(err => {
        document.getElementById('cap-list').innerHTML =
            `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
    });
}

async function _toggleCapability(name, enable) {
    try {
        if (enable) {
            await API.enableCapability(name);
        } else {
            await API.disableCapability(name);
        }
        // Refresh
        renderCapabilityList(document.getElementById('content'));
    } catch (err) {
        alert(`Failed: ${err.message}`);
    }
}
