/**
 * Gallery — starter templates and examples that create authored drafts.
 */
function renderGallery(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Gallery</h2><p>Start from reusable workflow examples without mixing them into your authored protocol catalog.</p>';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'protocol-surface-shell';
    container.appendChild(content);

    async function _createDraft(payload) {
        const result = await API.createProtocolDraft(payload);
        const protocolId = String(result?.protocol?.protocol_id || '').trim();
        Router.navigate(protocolId ? `/ui/protocols?protocol_id=${encodeURIComponent(protocolId)}&protocol_view=design` : '/ui/protocols');
    }

    function _buildTemplateCard(template) {
        const card = document.createElement('section');
        card.className = 'protocol-template-card';
        const title = document.createElement('strong');
        title.textContent = template.display_name || template.slug || 'Template';
        card.appendChild(title);
        const body = document.createElement('p');
        body.textContent = template.description || 'Reusable workflow starter.';
        card.appendChild(body);
        const stats = document.createElement('div');
        stats.className = 'protocol-template-meta';
        stats.textContent = [
            `${template.participant_count || 0} participants`,
            `${template.stage_count || 0} stages`,
            `${template.artifact_count || 0} artifacts`,
        ].join(' · ');
        card.appendChild(stats);
        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        const useBtn = document.createElement('button');
        useBtn.type = 'button';
        useBtn.className = 'btn btn-primary';
        useBtn.textContent = 'Use template';
        useBtn.addEventListener('click', () => {
            void _createDraft({
                source_kind: 'template',
                template_slug: template.slug,
            }).catch((err) => {
                UI.reportError('Failed to create a template-based protocol draft', err, {
                    context: 'Gallery protocol draft create failed',
                });
            });
        });
        actions.appendChild(useBtn);
        card.appendChild(actions);
        return card;
    }

    async function bootstrap() {
        UI.reconcileChildren(content, [UI.renderEmptyState('Loading gallery…', true)]);
        try {
            const templates = await API.listProtocolTemplates();
            const shell = document.createElement('section');
            shell.className = 'editor-panel protocol-panel';
            const title = document.createElement('div');
            title.className = 'editor-section-title';
            title.textContent = 'Protocol examples';
            shell.appendChild(title);
            const note = document.createElement('p');
            note.className = 'quiet-note';
            note.textContent = 'Examples stay here so your authored definitions list only shows drafts and published workflows that belong to your team.';
            shell.appendChild(note);

            const actions = document.createElement('div');
            actions.className = 'editor-actions';
            const blankBtn = document.createElement('button');
            blankBtn.type = 'button';
            blankBtn.className = 'btn';
            blankBtn.textContent = 'Start blank';
            blankBtn.addEventListener('click', () => {
                void _createDraft({ source_kind: 'blank' }).catch((err) => {
                    UI.reportError('Failed to create a blank protocol draft', err, {
                        context: 'Gallery blank protocol draft create failed',
                    });
                });
            });
            actions.appendChild(blankBtn);
            shell.appendChild(actions);

            const grid = document.createElement('div');
            grid.className = 'protocol-template-grid';
            if (Array.isArray(templates) && templates.length) {
                templates.forEach((template) => grid.appendChild(_buildTemplateCard(template)));
            } else {
                grid.appendChild(UI.renderEmptyState('No starter templates are available in this registry.', true));
            }
            shell.appendChild(grid);
            UI.reconcileChildren(content, [shell]);
        } catch (err) {
            UI.reconcileChildren(content, [UI.createErrorCard('Failed to load the Gallery: ' + err.message, bootstrap)]);
        }
    }

    container.__routeReady = bootstrap();
}
