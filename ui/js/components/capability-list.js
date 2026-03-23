/**
 * Capability list — global capability overrides with toggle switches.
 */
function renderCapabilityList(container) {
    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Capabilities</h2><p>Global capability overrides</p>';
    container.appendChild(header);

    const listEl = document.createElement('div');
    listEl.id = 'cap-list';
    container.appendChild(listEl);

    function loadCapabilities() {
        listEl.textContent = '';
        _renderSkeletons(listEl, 4, 'card');

        API.listCapabilities().then(caps => {
            listEl.textContent = '';
            if (!caps || caps.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'No capabilities declared';
                listEl.appendChild(empty);
                return;
            }

            caps.forEach(c => {
                const card = document.createElement('div');
                card.className = 'card';

                const row = document.createElement('div');
                row.className = 'card-row';

                const info = document.createElement('div');
                const title = document.createElement('div');
                title.className = 'card-title';
                title.textContent = c.name || c.capability_name || '';
                info.appendChild(title);

                if (c.declared_by_agents && c.declared_by_agents.length > 0) {
                    const sub = document.createElement('div');
                    sub.className = 'card-subtitle';
                    sub.textContent = 'Declared by: ' + c.declared_by_agents.join(', ');
                    info.appendChild(sub);
                }

                row.appendChild(info);

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
                row.appendChild(toggle);

                card.appendChild(row);
                listEl.appendChild(card);

                // Toggle handler with confirmation
                checkbox.addEventListener('change', () => {
                    const newEnabled = checkbox.checked;
                    const action = newEnabled ? 'enable' : 'disable';
                    // Revert immediately — confirm callback will set final state
                    checkbox.checked = !newEnabled;
                    _showConfirm(
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
                                console.error('Toggle capability failed', err);
                            }
                            checkbox.disabled = false;
                        }
                    );
                });
            });
        }).catch(err => {
            listEl.textContent = '';
            _renderError(listEl, 'Failed: ' + err.message, loadCapabilities);
        });
    }

    loadCapabilities();

    return function cleanup() {};
}
