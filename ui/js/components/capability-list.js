/**
 * Capability list — global capability overrides with toggle switches.
 */
function renderCapabilityList(container) {
    const cleanups = UI.beginCleanupScope();
    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Capabilities</h2><p>Global capability overrides</p>';
    container.appendChild(header);

    const listEl = document.createElement('div');
    listEl.id = 'cap-list';
    listEl.className = 'list-container list-container-loose';
    container.appendChild(listEl);

    function loadCapabilities() {
        listEl.textContent = '';
        UI.renderSkeletons(listEl, 4, 'row');

        API.listCapabilities().then(caps => {
            listEl.textContent = '';
            if (!caps || caps.length === 0) {
                listEl.appendChild(UI.renderEmptyState('No capabilities declared'));
                return;
            }

            caps.forEach(c => {
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
                listEl.appendChild(row);

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
            });
        }).catch(err => {
            listEl.textContent = '';
            UI.renderError(listEl, 'Failed: ' + err.message, loadCapabilities);
        });
    }

    loadCapabilities();

    // WS: reload on heartbeat (capabilities come from agent registrations)
    let reloadDebounce = null;
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'heartbeat') {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadCapabilities, 3000);
        }
    });
    cleanups.add(() => clearTimeout(reloadDebounce));
    cleanups.add(unsub);
}
