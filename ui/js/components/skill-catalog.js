/**
 * Skill catalog — runtime skills list via API.listSkills().
 */
function renderSkillCatalog(container) {
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
    searchInput.placeholder = 'Search skills...';
    searchInput.type = 'text';
    container.appendChild(searchInput);

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
        _renderSkeletons(listEl, 4, 'card');

        API.listSkills().then(data => {
            const skills = Array.isArray(data) ? data : (data.skills || []);
            allSkills = skills;
            renderList();
        }).catch(err => {
            listEl.textContent = '';
            _renderError(listEl, 'Failed: ' + err.message, loadSkills);
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
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = allSkills.length === 0 ? 'No skills installed' : 'No skills match search';
            listEl.appendChild(empty);
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

            if (s.status) {
                const badge = document.createElement('span');
                badge.className = 'badge badge-' + s.status;
                badge.textContent = s.status;
                row.appendChild(badge);
            }

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

    return function cleanup() {
        clearTimeout(searchTimeout);
        clearTimeout(reloadDebounce);
        unsub();
    };
}
