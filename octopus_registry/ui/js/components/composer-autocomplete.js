function _parseConversationTargetSelector(raw) {
    const text = String(raw || '').trim();
    if (!text.startsWith('@')) return null;
    const body = text.slice(1);
    if (body.startsWith('skill:')) {
        const value = body.slice(6).trim();
        return value ? { kind: 'skill', value } : null;
    }
    if (body.startsWith('role:')) {
        const value = body.slice(5).trim();
        return value ? { kind: 'role', value } : null;
    }
    const value = body.trim();
    if (!value) return null;
    return { kind: 'agent', value };
}

function _leadingConversationTargetToken(raw) {
    const text = String(raw || '').trim();
    if (!text.startsWith('@')) return '';
    const token = text.split(/\s+/, 1)[0] || '';
    return token.trim();
}

function _extractConversationTargetSelectorMessage(raw) {
    const text = String(raw || '').trim();
    const selectorToken = _leadingConversationTargetToken(text);
    if (!selectorToken) return null;
    const selector = _parseConversationTargetSelector(selectorToken);
    if (!selector) return null;
    const instructions = text.slice(selectorToken.length).trim();
    if (!instructions) return null;
    return { selector, instructions };
}

function _replaceLeadingConversationSelector(raw, selectorLabel) {
    const text = String(raw || '').trimStart();
    const token = _leadingConversationTargetToken(text);
    if (!token) return selectorLabel + ' ';
    const remainder = text.slice(token.length).trimStart();
    return selectorLabel + (remainder ? ` ${remainder}` : ' ');
}

function _formatConversationTargetLabel(selector) {
    if (!selector) return '';
    if (selector.kind === 'agent') {
        return '@' + (selector.preferred_agent_id || selector.value);
    }
    return '@' + selector.kind + ':' + selector.value;
}
