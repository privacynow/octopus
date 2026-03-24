/**
 * Provider guidance editor — view, edit, and manage provider guidance lifecycle.
 */
function renderGuidanceEditor(container) {
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Provider Guidance</h2><p>Manage system prompt guidance per provider</p>';
    container.appendChild(header);

    // Provider selector
    const selectorBar = document.createElement('div');
    selectorBar.className = 'filter-bar';

    const providerSelect = document.createElement('select');
    providerSelect.setAttribute('aria-label', 'Guidance provider');
    providerSelect.innerHTML =
        '<option value="claude">Claude</option>' +
        '<option value="codex">Codex</option>';
    selectorBar.appendChild(providerSelect);
    container.appendChild(selectorBar);

    const contentEl = document.createElement('div');
    contentEl.style.marginTop = '16px';
    container.appendChild(contentEl);

    let currentProvider = 'claude';

    providerSelect.addEventListener('change', () => {
        currentProvider = providerSelect.value;
        loadGuidance();
    });

    function loadGuidance() {
        contentEl.textContent = '';
        UI.renderSkeletons(contentEl, 2, 'card');

        API.getGuidance(currentProvider).then(data => {
            contentEl.textContent = '';
            renderGuidanceContent(data);
        }).catch(err => {
            contentEl.textContent = '';
            UI.renderError(contentEl, 'Failed: ' + err.message, loadGuidance);
        });
    }

    function renderGuidanceContent(data) {
        const guidance = data.guidance || data;

        // Status card
        const statusCard = document.createElement('div');
        statusCard.className = 'card';
        const statusRow = document.createElement('div');
        statusRow.className = 'card-row';
        const statusInfo = document.createElement('div');

        const statusTitle = document.createElement('div');
        statusTitle.className = 'card-title';
        statusTitle.textContent = currentProvider + ' guidance';
        statusInfo.appendChild(statusTitle);

        const statusSub = document.createElement('div');
        statusSub.className = 'card-subtitle';
        statusSub.textContent = 'Status: ' + (guidance.status || guidance.lifecycle_status || 'draft');
        statusInfo.appendChild(statusSub);

        statusRow.appendChild(statusInfo);

        if (guidance.status || guidance.lifecycle_status) {
            const badge = document.createElement('span');
            badge.className = 'badge badge-' + (guidance.status || guidance.lifecycle_status);
            badge.textContent = guidance.status || guidance.lifecycle_status;
            statusRow.appendChild(badge);
        }

        statusCard.appendChild(statusRow);
        contentEl.appendChild(statusCard);

        // Draft editor
        const editorCard = document.createElement('div');
        editorCard.className = 'card';
        editorCard.style.padding = '16px';

        const label = document.createElement('div');
        label.className = 'detail-label';
        label.textContent = 'System Prompt Draft';
        editorCard.appendChild(label);

        const textarea = document.createElement('textarea');
        textarea.className = 'guidance-textarea';
        textarea.rows = 12;
        textarea.value = guidance.draft_body || guidance.instruction_body || guidance.body || '';
        textarea.style.width = '100%';
        textarea.style.fontFamily = 'monospace';
        textarea.style.fontSize = '13px';
        textarea.style.padding = '8px';
        textarea.style.border = '1px solid var(--border-color, #333)';
        textarea.style.borderRadius = '4px';
        textarea.style.backgroundColor = 'var(--bg-secondary, #1e1e1e)';
        textarea.style.color = 'var(--text-primary, #e0e0e0)';
        textarea.style.resize = 'vertical';
        editorCard.appendChild(textarea);

        const actions = document.createElement('div');
        actions.className = 'card-actions';
        actions.style.marginTop = '12px';
        actions.style.display = 'flex';
        actions.style.gap = '8px';

        // Save draft
        const saveBtn = document.createElement('button');
        saveBtn.className = 'btn btn-primary btn-sm';
        saveBtn.textContent = 'Save Draft';
        saveBtn.addEventListener('click', async () => {
            saveBtn.disabled = true;
            try {
                await API.updateGuidanceDraft(currentProvider, { body: textarea.value });
                saveBtn.textContent = 'Saved';
                setTimeout(() => { saveBtn.textContent = 'Save Draft'; }, 2000);
            } catch (err) {
                UI.reportError('Failed to save the draft', err, { context: 'Guidance save draft failed' });
            }
            saveBtn.disabled = false;
        });
        actions.appendChild(saveBtn);

        // Preview
        const previewBtn = document.createElement('button');
        previewBtn.className = 'btn btn-sm';
        previewBtn.textContent = 'Preview';
        previewBtn.addEventListener('click', async () => {
            previewBtn.disabled = true;
            try {
                const result = await API.previewGuidance(currentProvider);
                const previewText = result.preview || result.system_prompt || JSON.stringify(result, null, 2);
                _showPreview(previewText);
            } catch (err) {
                UI.reportError('Failed to preview the guidance', err, { context: 'Guidance preview failed' });
            }
            previewBtn.disabled = false;
        });
        actions.appendChild(previewBtn);

        // Submit
        const submitBtn = document.createElement('button');
        submitBtn.className = 'btn btn-sm';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', async () => {
            submitBtn.disabled = true;
            try {
                await API.submitGuidance(currentProvider);
                loadGuidance();
            } catch (err) {
                UI.reportError('Failed to submit the guidance', err, { context: 'Guidance submit failed' });
            }
            submitBtn.disabled = false;
        });
        actions.appendChild(submitBtn);

        // Publish
        const publishBtn = document.createElement('button');
        publishBtn.className = 'btn btn-sm btn-primary';
        publishBtn.textContent = 'Publish';
        publishBtn.addEventListener('click', async () => {
            UI.showConfirm('Publish Guidance', 'Publish this guidance to all active conversations?', async () => {
                publishBtn.disabled = true;
                try {
                    await API.publishGuidance(currentProvider);
                    loadGuidance();
                } catch (err) {
                    UI.reportError('Failed to publish the guidance', err, { context: 'Guidance publish failed' });
                }
                publishBtn.disabled = false;
            });
        });
        actions.appendChild(publishBtn);

        editorCard.appendChild(actions);
        contentEl.appendChild(editorCard);
    }

    function _showPreview(text) {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';
        dialog.style.maxWidth = '700px';
        dialog.style.maxHeight = '80vh';
        dialog.style.overflow = 'auto';

        const h3 = document.createElement('h3');
        h3.textContent = 'System Prompt Preview';
        dialog.appendChild(h3);

        const pre = document.createElement('pre');
        pre.style.whiteSpace = 'pre-wrap';
        pre.style.fontSize = '12px';
        pre.textContent = text;
        dialog.appendChild(pre);

        const closeBtn = document.createElement('button');
        closeBtn.className = 'btn';
        closeBtn.textContent = 'Close';
        closeBtn.addEventListener('click', () => overlay.remove());
        dialog.appendChild(closeBtn);

        overlay.appendChild(dialog);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.remove();
        });
        document.body.appendChild(overlay);
    }

    loadGuidance();

}
