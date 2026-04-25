/**
 * Routing diagnostics - global routing-skill overrides with toggle switches.
 */
function renderRoutingPolicyList(container) {
    const cleanups = UI.beginCleanupScope();
    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Routing Diagnostics</h2><p>Operator controls for advertised capabilities. Disabled capabilities are excluded from discovery and direct assignment even if bots expose them.</p>';
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

    async function loadRoutingSkills() {
        try {
            const skills = await API.listRoutingSkills();
            if (!skills || skills.length === 0) {
                UI.clearMemoizedRender(listEl);
                UI.reconcileChildren(listEl, [UI.renderEmptyState('No routing skills are currently advertised by connected bots.', true)]);
                return;
            }

            UI.memoizedRender(listEl, skills, (nextSkills) => nextSkills.map((skill, index) => {
                // Toggle switch
                const enabled = skill.enabled !== false;
                const skillName = skill.name || skill.skill_name;

                const toggle = document.createElement('label');
                toggle.className = 'toggle-switch';

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.checked = enabled;

                const slider = document.createElement('span');
                slider.className = 'slider';

                toggle.appendChild(checkbox);
                toggle.appendChild(slider);
                checkbox.setAttribute('aria-label', `${enabled ? 'Disable' : 'Enable'} routing skill ${skillName}`);

                const row = UI.renderSettingsRow({
                    label: skill.name || skill.skill_name || '',
                    sublabel: skill.advertised_by_agents && skill.advertised_by_agents.length > 0
                        ? 'Advertised by: ' + skill.advertised_by_agents.join(', ')
                        : '',
                    control: toggle,
                });
                row.dataset.key = skillName || `routing-skill-${index}`;

                // Toggle handler with confirmation
                checkbox.addEventListener('change', () => {
                    const newEnabled = checkbox.checked;
                    const action = newEnabled ? 'enable' : 'disable';
                    // Revert immediately — confirm callback will set final state
                    checkbox.checked = !newEnabled;
                    UI.showConfirm(
                        (newEnabled ? 'Enable' : 'Disable') + ' Routing Skill',
                        'Are you sure you want to ' + action + ' routing for "' + skillName + '"?',
                        async () => {
                            checkbox.disabled = true;
                            try {
                                if (newEnabled) {
                                    await API.enableRoutingSkill(skillName);
                                } else {
                                    await API.disableRoutingSkill(skillName);
                                }
                                checkbox.checked = newEnabled;
                            } catch (err) {
                                checkbox.checked = !newEnabled;
                                UI.reportError('Failed to update routing policy', err, { context: 'Toggle routing skill failed' });
                            }
                            checkbox.disabled = false;
                        }
                    );
                });
                return row;
            }), {
                signatureFn(nextSkills) {
                    return (nextSkills || []).map((item) => ({
                        name: String(item.name || item.skill_name || ''),
                        enabled: item.enabled !== false,
                        advertisedBy: Array.isArray(item.advertised_by_agents) ? item.advertised_by_agents.join('|') : '',
                    }));
                },
            });
        } catch (err) {
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load routing policy: ' + err.message, loadRoutingSkills)]);
        }
    }

    container.__routeReady = loadRoutingSkills();
    UI.subscribeWithRefresh(cleanups, 'agents', loadRoutingSkills, 600);
}
