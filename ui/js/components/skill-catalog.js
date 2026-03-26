/**
 * Skill catalog — dense installable runtime skill roster.
 */
function renderSkillCatalog(container) {
    const cleanups = UI.beginCleanupScope();
    let searchTimeout = null;
    let currentQ = '';
    let allSkills = [];

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Skills</h2>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const workbench = document.createElement('section');
    workbench.className = 'workbench-panel';
    shell.appendChild(workbench);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    workbench.appendChild(controls);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search skills';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search skills');
    controls.appendChild(searchInput);

    const listWrap = document.createElement('section');
    listWrap.className = 'list-shell';
    shell.appendChild(listWrap);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    listWrap.appendChild(listEl);

    function renderList() {
        let filtered = allSkills;
        if (currentQ) {
            filtered = allSkills.filter((skill) => {
                const haystack = [
                    skill.slug || skill.name || '',
                    skill.description || skill.display_name || '',
                ].join(' ').toLowerCase();
                return haystack.includes(currentQ);
            });
        }

        if (!filtered.length) {
            UI.reconcileChildren(listEl, [
                UI.renderEmptyState(allSkills.length ? 'No skills match this search.' : 'No runtime skills available.', true),
            ]);
            return;
        }

        const rows = filtered.map((skill) => {
            const shellRow = document.createElement('div');
            shellRow.className = 'list-row-shell';
            shellRow.dataset.key = skill.slug || skill.name || skill.display_name || '';

            const sub = document.createElement('span');
            sub.textContent = skill.description || skill.display_name || 'Runtime skill';

            const row = UI.renderListRow({
                label: skill.slug || skill.name || '',
                sublabelNode: sub,
                badgeText: (skill.status || '').trim() || '',
                badgeClass: skill.status ? 'badge-' + skill.status : '',
            });
            shellRow.appendChild(row);

            const skillName = skill.slug || skill.name || '';
            const isInstalled = ['installed', 'published', 'active'].includes(String(skill.status || '').trim());
            const actionBtn = document.createElement('button');
            actionBtn.type = 'button';
            actionBtn.className = `btn btn-sm list-row-action${isInstalled ? ' btn-danger' : ' btn-primary'}`;
            actionBtn.textContent = isInstalled ? 'Uninstall' : 'Install';
            actionBtn.addEventListener('click', async () => {
                actionBtn.disabled = true;
                actionBtn.textContent = isInstalled ? 'Uninstalling…' : 'Installing…';
                try {
                    if (isInstalled) {
                        await API.uninstallSkill(skillName);
                    } else {
                        await API.installSkill(skillName);
                    }
                    loadSkills();
                } catch (err) {
                    actionBtn.disabled = false;
                    actionBtn.textContent = isInstalled ? 'Uninstall' : 'Install';
                    UI.reportError('Failed to update the skill', err, { context: 'Skill action failed' });
                }
            });
            shellRow.appendChild(actionBtn);
            return shellRow;
        });

        UI.reconcileChildren(listEl, rows);
    }

    function loadSkills({ soft = false } = {}) {
        if (!soft || !allSkills.length) {
            UI.reconcileChildren(listEl, UI.createSkeletonNodes(5, 'row'));
        }

        API.listSkills().then((data) => {
            allSkills = Array.isArray(data) ? data : (data.skills || []);
            renderList();
        }).catch((err) => {
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load skills: ' + err.message, loadSkills)]);
        });
    }

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentQ = searchInput.value.trim().toLowerCase();
            renderList();
        }, 250);
    });

    loadSkills();

    let reloadDebounce = null;
    const unsub = WS.subscribe('agents', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadSkills({ soft: true }), 600);
    });

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
    cleanups.add(unsub);
}
