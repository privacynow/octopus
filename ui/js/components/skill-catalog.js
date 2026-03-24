/**
 * Skill catalog — runtime skills list with install/uninstall actions.
 */
function renderSkillCatalog(container) {
    const cleanups = UI.beginCleanupScope();
    let searchTimeout = null;
    let currentQ = '';

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Skills</h2><p>Runtime skill catalog</p>';
    container.appendChild(header);

    // Search
    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search skills';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search skills');
    searchInput.setAttribute('title', 'Press / to focus search');
    container.appendChild(searchInput);

    const searchHint = document.createElement('div');
    searchHint.className = 'search-shortcut-hint search-shortcut-inline';
    searchHint.textContent = 'Shortcut: /';
    container.appendChild(searchHint);

    const listEl = document.createElement('div');
    listEl.style.marginTop = '16px';
    container.appendChild(listEl);

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentQ = searchInput.value.trim().toLowerCase();
            renderList();
        }, 300);
    });

    let allSkills = [];

    function loadSkills() {
        listEl.textContent = '';
        UI.renderSkeletons(listEl, 4, 'card');

        API.listSkills().then(data => {
            const skills = Array.isArray(data) ? data : (data.skills || []);
            allSkills = skills;
            renderList();
        }).catch(err => {
            listEl.textContent = '';
            UI.renderError(listEl, 'Failed: ' + err.message, loadSkills);
        });
    }

    function renderList() {
        listEl.textContent = '';

        let filtered = allSkills;
        if (currentQ) {
            filtered = allSkills.filter(s => {
                const name = (s.slug || s.name || '').toLowerCase();
                const desc = (s.description || s.display_name || '').toLowerCase();
                return name.includes(currentQ) || desc.includes(currentQ);
            });
        }

        if (filtered.length === 0) {
            listEl.appendChild(UI.renderEmptyState(allSkills.length === 0 ? 'No skills available' : 'No skills match search'));
            return;
        }

        filtered.forEach(s => {
            const card = document.createElement('div');
            card.className = 'card';

            const row = document.createElement('div');
            row.className = 'card-row';

            const info = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'card-title';
            title.textContent = s.slug || s.name || '';
            info.appendChild(title);

            const sub = document.createElement('div');
            sub.className = 'card-subtitle';
            sub.textContent = s.description || s.display_name || '';
            info.appendChild(sub);

            row.appendChild(info);

            const actions = document.createElement('div');
            actions.className = 'card-actions';

            if (s.status) {
                const badge = document.createElement('span');
                badge.className = 'badge badge-' + s.status;
                badge.textContent = s.status;
                actions.appendChild(badge);
            }

            const skillName = s.slug || s.name || '';
            const isInstalled = s.status === 'installed' || s.status === 'published' || s.status === 'active';

            const actionBtn = document.createElement('button');
            actionBtn.className = 'btn btn-sm' + (isInstalled ? ' btn-danger' : ' btn-primary');
            actionBtn.textContent = isInstalled ? 'Uninstall' : 'Install';
            actionBtn.addEventListener('click', async () => {
                actionBtn.disabled = true;
                actionBtn.textContent = isInstalled ? 'Uninstalling...' : 'Installing...';
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
            actions.appendChild(actionBtn);

            row.appendChild(actions);
            card.appendChild(row);
            listEl.appendChild(card);
        });
    }

    loadSkills();

    // WS: reload on heartbeat (skills may change on agent registration)
    let reloadDebounce = null;
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'heartbeat') {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadSkills, 3000);
        }
    });

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
    cleanups.add(unsub);
}
