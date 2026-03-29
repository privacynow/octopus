/**
 * Capability list — global capability overrides with toggle switches.
 */
function renderCapabilityList(container) {
    const cleanups = UI.beginCleanupScope();
    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Capabilities</h2>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const listWrap = document.createElement('div');
    listWrap.className = 'list-shell';
    shell.appendChild(listWrap);

    const listEl = document.createElement('div');
    listEl.id = 'cap-list';
    listEl.className = 'list-container';
    listWrap.appendChild(listEl);

    async function loadCapabilities() {
        try {
            const caps = await API.listCapabilities();
            if (!caps || caps.length === 0) {
                UI.clearMemoizedRender(listEl);
                UI.reconcileChildren(listEl, [UI.renderEmptyState('No capabilities declared.', true)]);
                return;
            }

            UI.memoizedRender(listEl, caps, (nextCaps) => nextCaps.map((c, index) => {
                // Toggle switch
                const enabled = c.enabled !== false;
                const capName = c.name || c.capability_name;

                const toggle = document.createElement('label');
                toggle.className = 'toggle-switch';

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.checked = enabled;

                const slider = document.createElement('span');
                slider.className = 'slider';

                toggle.appendChild(checkbox);
                toggle.appendChild(slider);
                checkbox.setAttribute('aria-label', `${enabled ? 'Disable' : 'Enable'} capability ${capName}`);

                const row = UI.renderSettingsRow({
                    label: c.name || c.capability_name || '',
                    sublabel: c.declared_by_agents && c.declared_by_agents.length > 0
                        ? 'Declared by: ' + c.declared_by_agents.join(', ')
                        : '',
                    control: toggle,
                });
                row.dataset.key = capName || `capability-${index}`;

                // Toggle handler with confirmation
                checkbox.addEventListener('change', () => {
                    const newEnabled = checkbox.checked;
                    const action = newEnabled ? 'enable' : 'disable';
                    // Revert immediately — confirm callback will set final state
                    checkbox.checked = !newEnabled;
                    UI.showConfirm(
                        (newEnabled ? 'Enable' : 'Disable') + ' Capability',
                        'Are you sure you want to ' + action + ' "' + capName + '"?',
                        async () => {
                            checkbox.disabled = true;
                            try {
                                if (newEnabled) {
                                    await API.enableCapability(capName);
                                } else {
                                    await API.disableCapability(capName);
                                }
                                checkbox.checked = newEnabled;
                            } catch (err) {
                                checkbox.checked = !newEnabled;
                                UI.reportError('Failed to update the capability', err, { context: 'Toggle capability failed' });
                            }
                            checkbox.disabled = false;
                        }
                    );
                });
                return row;
            }), {
                signatureFn(nextCaps) {
                    return (nextCaps || []).map((item) => ({
                        name: String(item.name || item.capability_name || ''),
                        enabled: item.enabled !== false,
                        declaredBy: Array.isArray(item.declared_by_agents) ? item.declared_by_agents.join('|') : '',
                    }));
                },
            });
        } catch (err) {
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load capabilities: ' + err.message, loadCapabilities)]);
        }
    }

    container.__routeReady = loadCapabilities();
    UI.subscribeWithRefresh(cleanups, 'agents', loadCapabilities, 600);
}
